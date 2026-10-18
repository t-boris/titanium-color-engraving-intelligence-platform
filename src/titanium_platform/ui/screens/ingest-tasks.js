/* Задачи гравировки на проверке пары (REQ-020): у каждого слоя — задача, выбранная для него, иначе задача всей работы,
   иначе задача его плана или платы, иначе та, что следует из режима LightBurn. Выбор не меняет измерений; при принятии
   задача записывается с каждым наблюдением. Рядом — метрики слоя со способом и основанием измерения. */
'use strict';
const IngestTasks = (() => {
  const {h, field, put, toast, fail, table} = App;

  /** Карточка «Задачи гравировки» для пары, ещё не принятой. */
  function card(pair, reload) {
    const layers = (pair.check?.layers || []).filter((l) => l.regions > 0 || l.measured_lab);
    const run = async (body) => {
      try { await put(`/pairs/${pair.id}/tasks`, body); toast('Задача записана', 'ok'); reload(); } catch (e) { fail(e); }
    };
    const work = Tasks.select(pair.work_task || '', {empty: pair.plan_task ? `по плану: ${Tasks.name(pair.plan_task.kind)}` : 'по слоям LightBurn',
      aria: 'Задача всей работы', onChange: (value) => run({layer_index: null, task: value || null})});
    const chosen = pair.layer_tasks || {};
    const rows = layers.map((l) => {
      const service = l.role && l.role !== 'test feature';
      const derived = l.task ? (l.task.basis === 'explicit' ? l.task.derived || l.task.kind : l.task.kind) : null;
      const choice = service ? h('span', {class: 'muted small'}, 'служебный слой: задача по его роли')
        : Tasks.select(chosen[String(l.index)] || '', {empty: 'не выбрана для слоя', extra: [['layer', `по слою LightBurn: ${Tasks.name(derived)}`]],
          aria: `Задача слоя ${l.name}`, onChange: (value) => run({layer_index: l.index, task: value || null})});
      return [l.name, Tasks.badge(l.task), choice, Tasks.metrics(l.metrics) || h('span', {class: 'muted small'}, 'не измерен')];
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Задачи гравировки'),
      h('p', {class: 'muted small'}, 'Для чего делался каждый слой. Результаты разных задач не смешиваются: залитый текст и заливка с одинаковыми '
        + 'настройками остаются разными записями. Если задача не выбрана, слой берёт задачу работы, плана или своего режима LightBurn.'),
      h('div', {class: 'grid g3'}, field('Задача всей работы', work)),
      table(['Слой', 'Задача сейчас', 'Выбор для слоя', 'Метрики: значение и основание'], rows, 'Слоёв нет'));
  }
  return {card};
})();
