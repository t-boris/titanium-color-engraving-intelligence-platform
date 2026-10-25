/* Планировщик экспериментов: цели, предложение следующей калибровочной платы, её принятие и результат (REQ-006, REQ-022,
   DEC-013, DEC-033). Расчёт офлайн и воспроизводим: то же состояние базы и то же зерно дают то же предложение. Предложение
   называет свой вопрос, ценность ответа и причину каждого набора; принятое создаёт платы (очистка — первой операцией), а его
   результат — измерения этих плат. Пояснение языковой модели необязательно и ничего не меняет. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, post, toast, fail, modal, table, num, labText, swatch, facts} = App;
  const REASON = {target: 'Целевой цвет', instability: 'Нестабильность', uncertainty: 'Высокая неопределённость', gap: 'Пробел в покрытии', repeat: 'Повтор'};
  const STATUS = {proposed: ['Предложено', ''], accepted: ['Принято: ждёт фото плат', 'warn'], rejected: ['Отклонено', 'bad'], done: ['Выполнено', 'ok']};
  const TASK = {line: 'линии', fill: 'заливки', tonal_image: 'тоновое изображение'};
  const when = (iso) => (iso ? new Date(iso).toLocaleString('ru-RU', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');
  const params = (p) => `${num(p.power, 1)}% · ${num(p.frequency, 0)} кГц · ${num(p.speed, 0)} мм/с · ${num(p.pulse_width, 0)} нс · шаг ${num(p.line_interval, 4)} мм · ${p.passes} проход(а)`;
  const stockName = (s) => [s.name, s.grade, s.batch].filter(Boolean).join(' · ') || 'титан без названия';

  function plateDialog(prop, reload) {
    const cw = h('input', {type: 'number', step: 'any', value: 6}), ch = h('input', {type: 'number', step: 'any', value: 5}), gap = h('input', {type: 'number', step: 'any', value: 1});
    modal('Принять предложение и создать платы', h('div', {class: 'stack'}, h('p', {}, 'Для каждой предложенной скорости создаётся плата по декартову произведению предложенных мощностей и частот; первой операцией файла идёт очистка поверхности. Дополнительные пересечения сетки помечаются: это не рекомендации планировщика. Платы делаются с линзой, установленной на лазере сейчас: она должна совпадать с линзой предложения. Измерения не создаются.'),
      h('div', {class: 'grid g3'}, field('Ширина ячейки, мм', cw), field('Высота ячейки, мм', ch), field('Зазор, мм', gap))), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Принять и создать платы', cls: 'primary', run: async (m) => {
        const made = await post(`/designer/proposals/${prop.id}/accept`, {cell_width: +cw.value, cell_height: +ch.value, gap: +gap.value});
        m.close(); toast(`Предложение принято, создано плат: ${made.plates.length}`, 'ok'); reload();
      }}]);
  }

  function rejectDialog(prop, reload) {
    const note = h('input', {placeholder: 'например: эти режимы уже проверены на другой заготовке'});
    modal('Отклонить предложение', h('div', {class: 'stack'}, h('p', {}, 'Отклонённое предложение остаётся в истории; плат по нему создать нельзя.'), field('Причина (необязательно)', note)), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Отклонить', cls: 'danger', run: async (m) => { await post(`/designer/proposals/${prop.id}/reject`, {note: note.value}); m.close(); toast('Предложение отклонено', 'ok'); reload(); }}]);
  }

  /** Измеренный исход одного набора: цвет на каждой принятой фотографии его ячейки и проверка цели (REQ-022 AC5). */
  function outcome(prop, r) {
    if (!r || !r.plate_id) return h('span', {class: 'muted'}, prop.boards.length ? 'ячейки нет на платах' : 'платы ещё не созданы');
    if (!r.measured.length) return h('span', {class: 'muted'}, 'ещё не измерен');
    return h('div', {class: 'stack small'}, r.measured.map((m) => h('span', {}, swatch(m.lab), ' ', labText(m.lab), ' · ', link('/analysis/' + m.pair_id, 'фото № ' + m.pair_id),
      m.comparable ? null : ' · без эталонной карты',
      m.target_check && m.target_check.delta_e != null ? ` · до цели ΔE ${num(m.target_check.delta_e, 1)}${m.target_check.within_tolerance == null ? '' : m.target_check.within_tolerance ? ' (в допуске)' : ' (вне допуска)'}` : null,
      m.delta_e_to_repeated_recipe != null ? ` · от первой гравировки ΔE ${num(m.delta_e_to_repeated_recipe, 1)}` : null)));
  }

  function platesBlock(prop) {
    if (!prop.plates.length) return null;
    return h('div', {class: 'stack'}, h('h4', {}, 'Платы и их фотографии'), table(['Плата', 'План', 'Фотографии'], prop.plates.map((p) => [
      `${p.experiment_id} · скорость ${num(p.speed, 0)} мм/с` + (p.deleted ? ' · удалена' : ''),
      p.plan_id ? link('/plans/' + p.plan_id, 'план № ' + p.plan_id) : '—',
      p.pairs.length ? h('div', {class: 'row'}, p.pairs.map((x) => h('span', {}, link(x.status === 'Accepted' ? '/analysis/' + x.id : '/ingest?pair=' + x.id, 'фото № ' + x.id), ' ',
        x.status === 'Accepted' ? pill('принято', 'ok') : pill('ждёт проверки', 'warn'))))
        : (p.plan_id ? link('/ingest?plan=' + p.plan_id, 'загрузить фото') : '—')])));
  }

  function explanationBlock(prop, reload) {
    const shown = prop.explanation ? h('div', {class: 'alert'}, h('strong', {}, 'Пояснение AI — гипотезы, не измерения. '), prop.explanation) : null;
    if (!prop.explanation_available) {
      return h('div', {class: 'stack'}, shown, h('p', {class: 'muted small'}, 'Пояснение AI недоступно: ключ языковой модели не настроен. Предложение полностью работает без него.'));
    }
    return h('div', {class: 'stack'}, shown, h('div', {class: 'row'}, btn(prop.explanation ? 'Обновить пояснение AI' : 'Получить пояснение AI', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await post(`/designer/proposals/${prop.id}/explanation`); toast('Пояснение получено', 'ok'); reload(); }
      catch (e) { fail(e); self.disabled = false; }
    }), h('span', {class: 'muted small'}, 'Модель только объясняет предложение и называет гипотезы; наборы параметров и данные она не меняет.')));
  }

  /** The parameter sets of a proposal (up to 40), a set a line: its number, settings, reason, target and whether it is measured; why it was
      chosen, its utility, target and measured result under the line (REQ-022 AC5); in the planner's order or by utility, twenty at a time (DEC-090). */
  function setsList(prop) {
    const results = new Map((prop.results || []).map((r) => [r.index, r]));
    const sets = prop.parameters.map((set, i) => ({set, i, result: results.get(i)}));
    const measured = ({result}) => (result && result.measured ? result.measured.length : 0);
    const target = (x) => (x.target_id ? 'цель № ' + x.target_id + (x.estimated_distance_to_target != null ? ` (прогноз ΔE ${num(x.estimated_distance_to_target)})` : '') : '—');
    return App.list({items: sets, key: (s) => s.i,
      row: (s) => [h('span', {class: 'muted small'}, `№ ${s.i + 1}`), h('span', {class: 'lst-text'}, params(s.set)), pill(REASON[s.set.reason] || s.set.reason),
        s.set.target_id ? h('span', {class: 'small'}, 'цель № ' + s.set.target_id) : null, measured(s) ? pill(`измерен: фото ${measured(s)}`, 'ok') : null],
      details: ({set: x, result}) => facts([['Почему выбран', x.rationale ? I18N.tr(x.rationale) : '—'], ['Полезность', num(x.utility)], ['Цель', target(x)],
        ['Результат', outcome(prop, result)]]),
      filters: [{key: 'reason', label: 'Причина', options: Object.entries(REASON), test: (s, v) => s.set.reason === v},
        ...(sets.some(measured) ? [{key: 'measured', label: 'Измерен', options: [['yes', 'измерены'], ['no', 'ещё нет']], test: (s, v) => (measured(s) > 0) === (v === 'yes')}] : [])],
      sorts: [['order', 'По порядку'], ['utility', 'Сначала полезные', (a, b) => (b.set.utility ?? -1) - (a.set.utility ?? -1)]]}).el;
  }

  function proposalCard(prop, reload) {
    const settings = prop.group ? ` · импульс ${prop.group.pulse_width} нс · шаг ${prop.group.line_interval} мм · проходов ${prop.group.passes}` : '';
    const [statusText, statusKind] = STATUS[prop.status] || [prop.status, ''];
    const setup = prop.setup ? `${prop.setup.device} · ${App.lensLabel(prop.setup.lens)}` : null;
    const stock = !prop.stock ? null : prop.stock.material ? stockName(prop.stock.material)
      : 'все заготовки, измеренные с этими настройками: ' + (prop.stock.measured.map((s) => `${stockName(s)} (${s.sets})`).join(', ') || 'пока нет');
    const history = prop.status_history.length ? h('details', {class: 'small'}, h('summary', {}, 'История статуса'), table(['Когда', 'Статус', 'Основание'],
      prop.status_history.map((e) => [when(e.at), (STATUS[e.to_status] || [e.to_status])[0], h('span', {}, I18N.tr(e.reason), e.note ? ` — «${e.note}»` : null,
        e.finding_id ? h('span', {}, ' · ', link('/findings?finding=' + e.finding_id, 'вывод № ' + e.finding_id)) : null)]), '', true)) : null;
    const actions = prop.status === 'proposed' ? h('div', {class: 'row'}, btn('Принять и создать платы', () => plateDialog(prop, reload), 'primary'),
      btn('Отклонить', () => rejectDialog(prop, reload), 'danger')) : null;
    return h('div', {class: 'card stack'},
      h('h3', {}, `Предложение № ${prop.id} · зерно ${prop.seed} · наборов ${prop.parameters.length}${settings}`, pill(statusText, statusKind)),
      (prop.questions || []).length ? h('div', {}, h('h4', {}, 'Вопрос'), h('ul', {}, prop.questions.map((q) => h('li', {}, I18N.tr(q))))) : null,
      (prop.worth || []).length ? h('div', {}, h('h4', {}, 'Чем ценен результат'), h('ul', {}, prop.worth.map((w) => h('li', {}, I18N.tr(w))))) : null,
      facts([['Задача', prop.task ? TASK[prop.task] || prop.task : null], ['Лазер и линза', setup], ['Титан', stock],
        ['По выводам анализа', prop.origins.length ? h('span', {}, prop.origins.map((o) => link('/findings?finding=' + o.finding_id, '№ ' + o.finding_id))) : null]]),
      h('p', {class: 'muted small'}, `Подпись состояния базы: ${prop.base_signature}. Тот же состав данных и то же зерно дают то же предложение.`),
      h('h4', {}, `Наборы параметров · ${prop.parameters.length}`), setsList(prop),
      actions, platesBlock(prop), explanationBlock(prop, reload), history);
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
    const [map, props, materials] = await Promise.all([get('/color-model?' + pick.query()), get('/designer/proposals?' + pick.query()), get('/materials')]);
    const reload = () => App.render({preserveScroll: true});
    const seed = h('input', {type: 'number', step: '1', value: 1729, 'aria-label': 'Зерно'}), size = h('input', {type: 'number', step: '1', min: '1', max: '40', value: 6, 'aria-label': 'Число наборов'});
    const chosen = props.find((p) => String(p.id) === ctx.query.proposal) || props[0] || null;
    const prop = chosen ? await get('/designer/proposals/' + chosen.id) : null;      // with its plates, photographs and results
    const group = prop?.group || {};
    const stock = h('select', {'aria-label': 'Титан'}, h('option', {value: ''}, 'все измеренные заготовки'),
      materials.map((m) => h('option', {value: m.id, selected: prop?.stock?.material_id === m.id}, stockName(m))));
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
        passes: +passes.value, seed: +seed.value, size: +size.value, material_id: stock.value === '' ? null : +stock.value});
        location.hash = `#/designer?${pick.route()}&proposal=${r.id}`; App.render(); } catch (e) { fail(e); }
    }, 'primary');
    let body = null;
    if (prop) {
      const others = props.length > 1 ? h('div', {class: 'toolbar'}, field('Другие предложения', h('select', {onChange: (e) => { location.hash = `#/designer?${pick.route()}&proposal=${e.target.value}`; }},
        props.map((p) => h('option', {value: p.id, selected: p.id === prop.id}, `№ ${p.id} · ${(STATUS[p.status] || [p.status])[0]} · ${when(p.created_at)}`))))) : null;
      body = h('div', {class: 'stack'}, others, ...prop.notes.map((n) => h('div', {class: 'alert warn'}, I18N.tr(n))),
        prop.unaddressed_targets.length ? h('div', {class: 'alert warn'}, 'Не адресованы цели: ' + prop.unaddressed_targets.join(', ')) : null,
        proposalCard(prop, reload));
    }
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Планировщик экспериментов'), h('p', {class: 'sub'}, 'Что измерить следующим: пробелы, неопределённость, нестабильность и цели.')),
      h('span', {class: 'spacer'})),
    h('div', {class: 'toolbar'}, h('div', {class: 'f-wrap'}, field('Лазер', pick.laser)), h('div', {class: 'f-wrap'}, field('Линза', pick.lens)),
      link('/colors?' + pick.route(), 'Модель цвета'), link('/findings', 'Выводы'), link('/ingest', 'Добавить измерения')),
    h('div', {class: 'card stack'}, h('h3', {}, 'Цели из недостижимых цветов'), targets),
    h('div', {class: 'card stack'}, h('h3', {}, 'Настройки работы и поиск по мощности, частоте и скорости'),
      h('p', {class: 'muted small'}, 'Длительность импульса, шаг линий и проходы одинаковы для всего предложения: модель строится только по измерениям с этими же настройками, этого лазера и этой линзы. Мощность, частота и скорость подбираются в пределах паспорта лазера.'),
      h('div', {class: 'grid g3'}, field('Длительность импульса, нс', pulse, 'только ступени этого лазера'), field('Шаг линий, мм', interval), field('Проходы слоя', passes),
        field('Титан', stock, 'одна заготовка — модель только по её измерениям')),
      h('div', {class: 'toolbar'}, field('Зерно', seed), field('Число наборов', size), propose,
        h('p', {class: 'toolbar-hint'}, 'То же зерно и те же данные дают то же предложение. Число наборов — от 1 до 40.'))),
    map.samples.length ? null : h('div', {class: 'alert warn'}, 'Добавьте измерения для анализа цветового пространства: пока наборы выбираются только по пробелам.'), body);
  }});
})();
