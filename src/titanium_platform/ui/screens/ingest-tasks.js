/* Pair review engraving tasks (REQ-020) use the layer, work, plan or LightBurn mode in that order.
   Selection does not change measurements; acceptance records the task with each observation. */
'use strict';
const IngestTasks = (() => {
  const {h, field, put, toast, fail} = App;
  let reopen = null;           // the layer whose task was just chosen: open again when the page is drawn after the change

  /** The card “Engraving tasks” of a pair not yet accepted. The layers are a short list (findings-you-can-manage-short-lists-re-check,
      REQ-005): a line per layer with its task now, the choice for the layer and the metrics under the line. */
  function card(pair, reload) {
    const layers = (pair.check?.layers || []).filter((l) => l.regions > 0 || l.measured_lab);
    const run = async (body) => {
      try { await put(`/pairs/${pair.id}/tasks`, body); toast('Task saved', 'ok'); reload(); } catch (e) { fail(e); }
    };
    const work = Tasks.select(pair.work_task || '', {empty: pair.plan_task ? `from plan: ${Tasks.name(pair.plan_task.kind)}` : 'from LightBurn layers',
      aria: 'Task for the whole work', onChange: (value) => run({layer_index: null, task: value || null})});
    const chosen = pair.layer_tasks || {};
    const service = (l) => l.role && l.role !== 'test feature';
    const details = (l) => {
      const derived = l.task ? (l.task.basis === 'explicit' ? l.task.derived || l.task.kind : l.task.kind) : null;
      const choice = service(l) ? h('span', {class: 'muted small'}, 'service layer: task follows its role')
        : Tasks.select(chosen[String(l.index)] || '', {empty: 'not selected for the layer', extra: [['layer', `from LightBurn layer: ${Tasks.name(derived)}`]],
          aria: `Task for layer ${l.name}`, onChange: (value) => { reopen = {pair: pair.id, key: String(l.index)}; run({layer_index: l.index, task: value || null}); }});
      return h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, field('Layer selection', choice)),
        h('div', {class: 'stack small'}, h('strong', {}, 'Metrics: value and evidence'), Tasks.metrics(l.metrics) || h('span', {class: 'muted small'}, 'not measured')));
    };
    const kinds = [...new Set(layers.map((l) => l.task && l.task.kind).filter(Boolean))];
    const list = App.list({id: `ingest-tasks:${pair.id}`, items: layers, key: (l) => l.index, empty: 'No layers', details,
      open: reopen && reopen.pair === pair.id ? reopen.key : null,
      row: (l) => [h('span', {class: 'lst-text', title: l.name}, l.name), Tasks.badge(l.task), l.measured_lab ? null : h('span', {class: 'muted small'}, 'not measured')],
      search: (l) => l.name,
      filters: kinds.length > 1 ? [{key: 'task', label: 'Current task', options: kinds.map((k) => [k, Tasks.name(k)]), test: (l, v) => (l.task && l.task.kind) === v}] : [],
      sorts: [['order', 'Original order', (a, b) => a.index - b.index]]});
    reopen = null;
    return h('div', {class: 'card stack'}, h('h3', {}, 'Engraving tasks'),
      h('p', {class: 'muted small'}, 'Purpose of each layer. Results from different tasks are kept separate: filled lettering and a fill with identical '
        + 'settings remain separate records. Without a selected task, the layer inherits the work, plan or LightBurn mode task. '
        + 'Select a layer to choose its task and see its metrics.'),
      h('div', {class: 'grid g3'}, field('Task for the whole work', work)),
      list.el);
  }
  return {card};
})();
