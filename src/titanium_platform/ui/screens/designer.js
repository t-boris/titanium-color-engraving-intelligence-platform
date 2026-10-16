/* Планировщик экспериментов: цели, предложение следующей калибровочной платы и её создание (REQ-006, DEC-013, DEC-033).
   Расчёт офлайн и воспроизводим: то же состояние базы и то же зерно дают то же предложение. Языковой модели нет. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, post, toast, fail, modal, table, num, labText, swatch} = App;
  const REASON = {target: 'Целевой цвет', instability: 'Нестабильность', uncertainty: 'Высокая неопределённость', gap: 'Пробел в покрытии'};
  const params = (p) => `${num(p.power, 1)}% · ${num(p.frequency, 0)} кГц · ${num(p.speed, 0)} мм/с · ${num(p.pulse_width, 0)} нс · шаг ${num(p.line_interval, 4)} мм · ${p.passes} проход(а)`;

  function plateDialog(prop, reload) {
    const cw = h('input', {type: 'number', step: 'any', value: 6}), ch = h('input', {type: 'number', step: 'any', value: 5}), gap = h('input', {type: 'number', step: 'any', value: 1});
    modal('Создать калибровочные платы', h('div', {class: 'stack'}, h('p', {}, 'Для каждой предложенной скорости создаётся плата по декартову произведению предложенных мощностей и частот. Дополнительные пересечения сетки помечаются: это не рекомендации планировщика. Измерения не создаются.'),
      h('div', {class: 'grid g3'}, field('Ширина ячейки, мм', cw), field('Высота ячейки, мм', ch), field('Зазор, мм', gap))), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Создать планы', cls: 'primary', run: async (m) => {
        const made = await post(`/designer/proposals/${prop.id}/plates`, {cell_width: +cw.value, cell_height: +ch.value, gap: +gap.value});
        m.close(); toast(`Создано плат: ${made.length}`, 'ok'); reload(made[0].plan_id);
      }}]);
  }

  App.register({id: 'designer', async render(ctx) {
    const profiles = await get('/profiles');
    if (!profiles.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала настройте профиль лазера'), link('/profiles', 'Профили'));
    const pid = +(ctx.query.profile || ctx.query.profileId || profiles[profiles.length - 1].id);
    const [map, props] = await Promise.all([get(`/profiles/${pid}/map`), get(`/profiles/${pid}/proposals`)]);
    const reload = (planId) => { if (planId) location.hash = '#/plans/' + planId; else App.render(); };
    const seed = h('input', {type: 'number', step: '1', value: 1729, 'aria-label': 'Зерно'}), size = h('input', {type: 'number', step: '1', min: '1', max: '40', value: 6, 'aria-label': 'Число наборов'});
    const currentProfile = profiles.find((p) => p.id === pid);
    const pulseDefault = currentProfile?.device?.passport?.pulse_steps?.map((x) => x.pulse_width_ns).join(' ') || '200';
    const pulseWidths = h('input', {value: pulseDefault}), lineIntervals = h('input', {value: '0.025 0.05 0.1'}), passCounts = h('input', {value: '1 2 3'});
    const picker = h('select', {'aria-label': 'Лазер + линза', onChange: (e) => { location.hash = '#/designer?profile=' + e.target.value; }}, profiles.map((p) => h('option', {value: p.id, selected: p.id === pid}, `${p.name}${p.device ? ` · ${p.device.name}` : ''}${p.lens ? ` · ${p.lens.name}` : ''}`)));
    const prop = props.find((p) => String(p.id) === ctx.query.proposal) || props[0] || null;
    const targets = map.targets.length ? table(['Цвет', 'Исходный план', 'Предложение'], map.targets.map((t) => [h('span', {}, swatch(t.lab), labText(t.lab)), link('/plans/' + t.source_plan_id, 'Исходная работа'), t.proposal_id ? '№ ' + t.proposal_id : 'ещё не адресована']))
      : h('p', {class: 'muted'}, 'Нет недостижимых цветов из работ. Подбор по пробелам остаётся доступен.');
    const propose = btn('Предложить плату', async () => {
      try { const r = await post('/designer/propose', {profile_id: pid, seed: +seed.value, size: +size.value,
        pulse_widths: pulseWidths.value, line_intervals: lineIntervals.value, passes: passCounts.value}); location.hash = `#/designer?profile=${pid}&proposal=${r.id}`; App.render(); } catch (e) { fail(e); }
    }, 'primary');
    let body = null;
    if (prop) {
      const rows = prop.parameters.map((x) => [params(x), pill(REASON[x.reason] || x.reason), num(x.utility), x.target_id ? 'цель № ' + x.target_id + (x.estimated_distance_to_target != null ? ` (прогноз ΔE ${num(x.estimated_distance_to_target)})` : '') : '—']);
      body = h('div', {class: 'stack'}, ...prop.notes.map((n) => h('div', {class: 'alert warn'}, I18N.tr(n))),
        prop.unaddressed_targets.length ? h('div', {class: 'alert warn'}, 'Не адресованы цели: ' + prop.unaddressed_targets.join(', ')) : null,
        h('div', {class: 'card'}, h('h3', {}, `Предложение № ${prop.id} · зерно ${prop.seed} · наборов ${prop.parameters.length}`),
          h('p', {class: 'muted small'}, `Подпись состояния базы: ${prop.base_signature}. Тот же состав данных и то же зерно дают то же предложение.`), table(['Набор параметров', 'Причина', 'Полезность', 'Цель'], rows),
          prop.explanation ? h('div', {class: 'alert'}, prop.explanation) : h('p', {class: 'muted small'}, 'Пояснение не подключено: предложение полностью работает без языковой модели.'),
          prop.boards.length ? h('p', {}, 'Платы созданы: ', prop.boards.map((b) => '№ ' + b).join(', ')) : btn('Создать калибровочные платы', () => plateDialog(prop, reload), 'primary')));
    }
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Планировщик экспериментов'), h('p', {class: 'sub'}, 'Что измерить следующим: пробелы, неопределённость, нестабильность и цели.')),
      h('span', {class: 'spacer'})),
    h('div', {class: 'toolbar'}, h('div', {class: 'f-wrap wide'}, field('Лазер + линза', picker)), link('/colors?profile=' + pid, 'Карта цветов'), link('/ingest', 'Добавить измерения')),
    h('div', {class: 'card stack'}, h('h3', {}, 'Цели из недостижимых цветов'), targets),
    h('div', {class: 'card stack'}, h('h3', {}, 'Диапазон поиска по шести параметрам'),
      h('p', {class: 'muted small'}, 'Мощность, частота и скорость выбираются в пределах паспорта. Для импульса используются ступени выбранного лазера; интервалы и проходы задаются для текущего подбора.'),
      h('div', {class: 'grid g3'}, field('Длительность импульса, нс', pulseWidths, 'числа через пробел или «;»'), field('Шаг линий, мм', lineIntervals), field('Проходы слоя', passCounts)),
      h('div', {class: 'toolbar'}, field('Зерно', seed), field('Число наборов', size), propose,
        h('p', {class: 'toolbar-hint'}, 'То же зерно и те же данные дают то же предложение. Число наборов — от 1 до 40.'))),
    map.samples.length ? null : h('div', {class: 'alert warn'}, 'Добавьте измерения для анализа цветового пространства: пока наборы выбираются только по пробелам.'), body);
  }});
})();
