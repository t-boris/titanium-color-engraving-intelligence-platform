/* Анализ после гравировки: сравнение результата с планом (REQ-001, REQ-013). Метрика зависит от режима плана. */
'use strict';
(() => {
  const {h, btn, link, pill, get, table, num, labText, swatch, facts} = App;

  function metrics(r) {
    const m = r.metrics || {};
    if (m.kind === 'brightness_contrast') {
      return facts([['Полос', m.bands], ['Плановый контраст (ΔL между самой тёмной и самой светлой)', num(m.planned_contrast, 1)], ['Измеренный контраст', num(m.measured_contrast, 1)],
        ['Средняя |ΔL|', num(m.mean_abs_delta_l, 2)], ['Монотонность по плановой яркости', m.monotonic ? 'соблюдена' : 'нарушена']]);
    }
    if (m.kind === 'delta_e_along_path') {
      return facts([['Полос', m.bands], ['Средний ΔE до плана', num(m.mean_delta_e)], ['Максимальный ΔE до плана', num(m.max_delta_e)],
        ['Среднее расстояние от траектории', num(m.mean_path_distance)], ['Максимальное расстояние от траектории', num(m.max_path_distance)]]);
    }
    if (m.kind === 'color_deviation') return facts([['Слоёв', m.layers], ['Средний ΔE', num(m.mean_delta_e)], ['Максимальный ΔE', num(m.max_delta_e)]]);
    return h('p', {class: 'muted'}, 'Плановое значение отсутствует: показаны только измерения.');
  }

  function rowsTable(r) {
    const tonal = r.mode === 'Tonal photo engraving', path = r.mode === 'Color-path photo engraving';
    const head = ['Слой', 'Параметры', 'Измеренный цвет', 'Плановый цвет', tonal ? 'ΔL' : 'ΔE', path ? 'От траектории' : 'Допуск', 'Уверенность', 'Ожидаемая ошибка', 'Стабильность'];
    return table(head, r.rows.map((x) => {
      const p = x.planned_prediction;
      const stab = x.knowledge ? (x.knowledge.stability.assessed ? 'дисперсия ' + num(x.knowledge.stability.variance) : 'не оценена') : '—';
      return [x.name || x.layer_index, `${num(x.parameters.power, 1)} % · ${num(x.parameters.frequency, 0)} кГц · ${num(x.parameters.speed, 0)} мм/с`,
        h('span', {}, swatch(x.measured_lab), labText(x.measured_lab)), x.planned_lab ? h('span', {}, swatch(x.planned_lab), labText(x.planned_lab)) : (x.note ? I18N.tr(x.note) : 'Плановый цвет отсутствует'),
        tonal ? num(x.delta_l) : num(x.delta_e), path ? num(x.path_distance) : x.within_tolerance == null ? '—' : x.within_tolerance ? pill('в допуске', 'ok') : pill('вне допуска', 'bad'),
        p ? num(p.confidence) : '—', p ? num(p.expected_delta_e) : '—', stab];
    }), 'Измерений нет');
  }

  App.register({id: 'analysis', async render(ctx) {
    const id = ctx.arg;
    let r;
    try { r = await get(`/pairs/${id}/report`); }
    catch (e) {
      return h('div', {class: 'card empty'}, h('h3', {}, 'Для отчёта нужны принятые наблюдения'), h('p', {}, e.message), link('/ingest?pair=' + id, 'Вернуться к проверке пары'), ' ', link('/ingest', 'Добавить наблюдение'));
    }
    const MODE = {'Calibration plate': 'Калибровочная плата', 'Discrete color engraving': 'Цветная гравировка', 'Tonal photo engraving': 'Тональная фотогравировка', 'Color-path photo engraving': 'Фотогравировка по цветовому пути'};
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Анализ после гравировки'), h('p', {class: 'sub'}, 'Режим: ' + (MODE[r.mode] || 'план не связан') + ' · выравнивание: ' + (r.alignment === 'markers' ? 'по маркерам' : r.alignment === 'manual' ? 'вручную по углам' : '—'))),
        h('span', {class: 'spacer'}), r.plan_id ? link('/plans/' + r.plan_id, 'Исходный план') : null, link('/colors', 'Карта цветов'), link('/designer', 'Следующий эксперимент'), link('/ingest?rephoto=' + id, 'Повторная фотография этого изделия')),
      h('div', {class: 'card stack'}, h('h3', {}, 'Результат'), metrics(r), r.tolerance == null ? null : h('p', {class: 'muted small'}, 'Допуск ΔE из профиля: ' + r.tolerance)),
      h('div', {class: 'card'}, h('h3', {}, 'Измерения по слоям'), rowsTable(r)),
      r.limitations.length ? h('div', {class: 'card stack'}, h('h3', {}, 'Ограничения'), r.limitations.map((m) => h('div', {class: 'alert warn'}, I18N.tr(m)))) : null);
  }});
})();
