/* Планировщик экспериментов: цели, предложение следующей калибровочной платы и её создание (REQ-006, DEC-013, DEC-033).
   Расчёт офлайн и воспроизводим: то же состояние базы и то же зерно дают то же предложение. Языковой модели нет. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, post, toast, fail, modal, table, num, labText, swatch} = App;
  const REASON = {target: 'Целевой цвет', instability: 'Нестабильность', uncertainty: 'Высокая неопределённость', gap: 'Пробел в покрытии'};
  const params = (p) => `${num(p.power, 1)}% · ${num(p.frequency, 0)} кГц · ${num(p.speed, 0)} мм/с · ${num(p.pulse_width, 0)} нс · шаг ${num(p.line_interval, 4)} мм · ${p.passes} проход(а)`;

  function plateDialog(prop, reload) {
    const cw = h('input', {type: 'number', step: 'any', value: 6}), ch = h('input', {type: 'number', step: 'any', value: 5}), gap = h('input', {type: 'number', step: 'any', value: 1});
    modal('Создать калибровочные платы', h('div', {class: 'stack'}, h('p', {}, 'Для каждой предложенной скорости создаётся плата по декартову произведению предложенных мощностей и частот. Дополнительные пересечения сетки помечаются: это не рекомендации планировщика. Платы делаются с линзой, установленной на лазере сейчас: она должна совпадать с линзой предложения. Измерения не создаются.'),
      h('div', {class: 'grid g3'}, field('Ширина ячейки, мм', cw), field('Высота ячейки, мм', ch), field('Зазор, мм', gap))), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Создать планы', cls: 'primary', run: async (m) => {
        const made = await post(`/designer/proposals/${prop.id}/plates`, {cell_width: +cw.value, cell_height: +ch.value, gap: +gap.value});
        m.close(); toast(`Создано плат: ${made.length}`, 'ok'); reload(made[0].plan_id);
      }}]);
  }

  /** Длительность импульса: только ступени выбранного лазера; 200 нс подставляется, лишь если лазер её предлагает (DEC-043). */
  function pulseSelect(device, wanted) {
    const steps = (device?.passport?.pulse_steps || []).map((x) => +x.pulse_width_ns);
    const value = steps.includes(+wanted) ? +wanted : steps.includes(200) ? 200 : null;
    return h('select', {'aria-label': 'Длительность импульса'}, h('option', {value: '', selected: value == null}, 'выберите'),
      steps.map((w) => h('option', {value: w, selected: w === value}, w + ' нс')));
  }

  App.register({id: 'designer', async render(ctx) {
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер'), link('/devices', 'Лазеры'));
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens, onChange: () => { location.hash = '#/designer?' + pick.route(); }});
    const [map, props] = await Promise.all([get('/color-model?' + pick.query()), get('/designer/proposals?' + pick.query())]);
    const reload = (planId) => { if (planId) location.hash = '#/plans/' + planId; else App.render(); };
    const seed = h('input', {type: 'number', step: '1', value: 1729, 'aria-label': 'Зерно'}), size = h('input', {type: 'number', step: '1', min: '1', max: '40', value: 6, 'aria-label': 'Число наборов'});
    const prop = props.find((p) => String(p.id) === ctx.query.proposal) || props[0] || null;
    const group = prop?.group || {};
    const pulse = pulseSelect(pick.device(), group.pulse_width);
    const interval = h('input', {type: 'number', step: 'any', min: '0', value: group.line_interval ?? 0.025, 'aria-label': 'Шаг линий'});
    const passes = h('input', {type: 'number', step: '1', min: '1', value: group.passes ?? 1, 'aria-label': 'Проходы слоя'});
    // the latest measurement of a plate cell made for the target (REQ-006): delta E and the verdict by the saved tolerance
    const checked = (c) => (!c ? 'ещё не измерена' : !c.comparable ? 'измерена без карты: не сравнима'
      : `ΔE ${num(c.delta_e, 1)}${c.within_tolerance == null ? ' · допуск не задан' : c.within_tolerance ? ' · в допуске' : ' · вне допуска'}`);
    const targets = map.targets.length ? table(['Цвет', 'Исходный план', 'Предложение', 'Проверка'], map.targets.map((t) => [h('span', {}, swatch(t.lab), labText(t.lab)), link('/plans/' + t.source_plan_id, 'Исходная работа'), t.proposal_id ? '№ ' + t.proposal_id : 'ещё не адресована',
      t.checks?.length ? link('/analysis/' + t.checks[0].pair_id, checked(t.checks[0])) : checked(null)]))
      : h('p', {class: 'muted'}, 'Нет недостижимых цветов из работ. Подбор по пробелам остаётся доступен.');
    const propose = btn('Предложить плату', async () => {
      if (pulse.value === '' || interval.value === '' || passes.value === '') return fail(new Error('Задайте длительность импульса, шаг линий и число проходов'));
      try { const r = await post('/designer/propose', {device_id: pick.deviceId(), lens_id: pick.lensId(), pulse_width: +pulse.value, line_interval: +interval.value,
        passes: +passes.value, seed: +seed.value, size: +size.value}); location.hash = `#/designer?${pick.route()}&proposal=${r.id}`; App.render(); } catch (e) { fail(e); }
    }, 'primary');
    let body = null;
    if (prop) {
      const rows = prop.parameters.map((x) => [params(x), pill(REASON[x.reason] || x.reason), num(x.utility), x.target_id ? 'цель № ' + x.target_id + (x.estimated_distance_to_target != null ? ` (прогноз ΔE ${num(x.estimated_distance_to_target)})` : '') : '—']);
      const settings = prop.group ? ` · импульс ${prop.group.pulse_width} нс · шаг ${prop.group.line_interval} мм · проходов ${prop.group.passes}` : '';
      body = h('div', {class: 'stack'}, ...prop.notes.map((n) => h('div', {class: 'alert warn'}, I18N.tr(n))),
        prop.unaddressed_targets.length ? h('div', {class: 'alert warn'}, 'Не адресованы цели: ' + prop.unaddressed_targets.join(', ')) : null,
        h('div', {class: 'card'}, h('h3', {}, `Предложение № ${prop.id} · зерно ${prop.seed} · наборов ${prop.parameters.length}${settings}`),
          h('p', {class: 'muted small'}, `Подпись состояния базы: ${prop.base_signature}. Тот же состав данных и то же зерно дают то же предложение.`), table(['Набор параметров', 'Причина', 'Полезность', 'Цель'], rows),
          prop.explanation ? h('div', {class: 'alert'}, prop.explanation) : h('p', {class: 'muted small'}, 'Пояснение не подключено: предложение полностью работает без языковой модели.'),
          prop.boards.length ? h('p', {}, 'Платы созданы: ', prop.boards.map((b) => '№ ' + b).join(', ')) : btn('Создать калибровочные платы', () => plateDialog(prop, reload), 'primary')));
    }
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Планировщик экспериментов'), h('p', {class: 'sub'}, 'Что измерить следующим: пробелы, неопределённость, нестабильность и цели.')),
      h('span', {class: 'spacer'})),
    h('div', {class: 'toolbar'}, h('div', {class: 'f-wrap'}, field('Лазер', pick.laser)), h('div', {class: 'f-wrap'}, field('Линза', pick.lens)),
      link('/colors?' + pick.route(), 'Модель цвета'), link('/ingest', 'Добавить измерения')),
    h('div', {class: 'card stack'}, h('h3', {}, 'Цели из недостижимых цветов'), targets),
    h('div', {class: 'card stack'}, h('h3', {}, 'Настройки работы и поиск по мощности, частоте и скорости'),
      h('p', {class: 'muted small'}, 'Длительность импульса, шаг линий и проходы одинаковы для всего предложения: модель строится только по измерениям с этими же настройками, этого лазера и этой линзы. Мощность, частота и скорость подбираются в пределах паспорта лазера.'),
      h('div', {class: 'grid g3'}, field('Длительность импульса, нс', pulse, 'только ступени этого лазера'), field('Шаг линий, мм', interval), field('Проходы слоя', passes)),
      h('div', {class: 'toolbar'}, field('Зерно', seed), field('Число наборов', size), propose,
        h('p', {class: 'toolbar-hint'}, 'То же зерно и те же данные дают то же предложение. Число наборов — от 1 до 40.'))),
    map.samples.length ? null : h('div', {class: 'alert warn'}, 'Добавьте измерения для анализа цветового пространства: пока наборы выбираются только по пробелам.'), body);
  }});
})();
