/* Карточки лазера: паспорт, ступени, документы, результаты и эксперименты (REQ-017). Расчёт рабочей точки — device-calc.js, экран — device.js. */
'use strict';
const DeviceView = (() => {
  const {h, btn, field, link, pill, del, post, toast, fail, confirmBox, table, facts, labText, num} = App;
  const g = (v, d = 3) => (v == null ? '—' : String(+(+v).toPrecision(d)));
  const size = (n) => (n < 1024 * 1024 ? Math.max(1, Math.round(n / 1024)) + ' КБ' : (n / 1024 / 1024).toFixed(1).replace('.', ',') + ' МБ');

  function passportCard(d) {
    const p = d.passport, r = p.repetition_rate_khz;
    return h('div', {class: 'card stack'}, h('h3', {}, 'Паспорт'),
      d.description ? h('details', {}, h('summary', {class: 'small muted'}, 'Описание лазера'), h('p', {class: 'muted'}, d.description)) : null,
      facts([['Производитель', d.manufacturer], ['Модель', d.model], ['Серийный номер', d.serial || 'не указан'], ['Номинальная мощность', p.rated_power_w + ' Вт' + (d.characterization.power_basis === 'measured' ? ` (у вашего экземпляра измерено ${d.characterization.effective_power_w} Вт)` : '')],
        ['Длина волны', p.wavelength_nm ? p.wavelength_nm + ' нм' : null], ['Частота повторения', `${r.min}–${r.max} кГц`],
        ['Q-Pulse по умолчанию', p.default_pulse_width_ns != null ? p.default_pulse_width_ns + ' нс (его LightBurn не пишет в файл слоя)' : 'не задан: слой без Q-Pulse в файле не сопоставим'],
        ['Наибольшая энергия импульса', p.max_pulse_energy_mj ? p.max_pulse_energy_mj + ' мДж' : null],
        // the spot is the installed lens's: measured with it, or calculated from it (REQ-019)
        ['Диаметр пятна на металле', d.characterization.spot_diameter_um != null
          ? `${g(d.characterization.spot_diameter_um)} мкм (${d.characterization.spot_basis === 'measured' ? 'измерено с установленной линзой' : 'рассчитано по линзе'})`
          : 'не задан: плотность энергии не считается']]),
      DeviceQuestions.card(d));
  }

  function stepsCard(d) {
    const rows = d.passport.pulse_steps.map((s) => [s.pulse_width_ns + ' нс', s.cutoff_khz == null ? 'CW: без среза' : s.cutoff_khz + ' кГц',
      s.cutoff_khz == null ? '—' : g(d.passport.rated_power_w / s.cutoff_khz) + ' мДж']);
    return h('details', {class: 'card stack'}, h('summary', {}, h('strong', {}, `Ступени длительности импульса и частоты среза: ${d.passport.pulse_steps.length}`)),
      h('p', {class: 'muted small'}, 'Лазер принимает только эти значения. Любое другое он игнорирует и оставляет прежнее, поэтому плата или план с другой длительностью не создаётся. '
        + 'Ниже частоты среза мощность падает пропорционально частоте. Энергия — расчёт по паспорту, не измерение.'),
      table(['Длительность импульса', 'Частота среза', 'Наибольшая энергия импульса'], rows, undefined, true));
  }

  /** The documents of a laser as the compact list (ux-growing-collections-p0, REQ-002): a line each, a search, the kind as a filter, an order,
      pages of twenty. A line opens to the file's preview and facts only when asked, so a hundred scans are not loaded at once; the document
      opened last stays in view as the pinned line when a search or a filter leaves it out. Every document stays reachable by «Открыть». */
  function documentsCard(d, reload) {
    let current = null;                                    // the document the operator opened last
    const url = (x) => `/api/devices/${d.id}/documents/${x.id}`;
    const day = (iso) => (iso || '').slice(0, 10);
    const open = (x) => h('a', {class: 'btn btn-small', href: url(x), target: '_blank', rel: 'noopener'}, 'Открыть');
    const items = App.list({id: 'device-documents.' + d.id, items: d.documents, key: (x) => x.id, className: 'doc-list',
      search: (x) => `${x.title} ${x.filename} ${DeviceForms.KIND[x.kind] || x.kind}`,
      row: (x) => [h('span', {class: 'lst-text', title: x.title}, x.title), pill(DeviceForms.KIND[x.kind] || x.kind),
        h('span', {class: 'muted small'}, x.filename), h('span', {class: 'muted small'}, size(x.size))],
      details: (x) => {
        current = x.id;
        const preview = x.media_type.startsWith('image/')
          ? h('a', {href: url(x), target: '_blank', rel: 'noopener'}, h('img', {src: url(x), alt: x.title, loading: 'lazy', style: 'max-width:220px;max-height:160px;object-fit:cover'})) : null;
        return h('div', {class: 'stack small'}, preview,
          facts([['Вид', DeviceForms.KIND[x.kind] || x.kind], ['Файл', x.filename], ['Размер', size(x.size)], ['Добавлен', day(x.created_at)]]));
      },
      actions: (x) => [open(x), btn('Удалить', () => confirmBox('Удалить документ', `«${x.title}». Файл будет удалён с диска, паспорт останется.`, 'Удалить',
        async () => { await del(`/devices/${d.id}/documents/${x.id}`); toast('Документ удалён', 'ok'); reload(d.id); }), 'btn-small danger')],
      filters: [{key: 'kind', label: 'Вид', select: true, options: DeviceForms.KINDS, test: (x, v) => x.kind === v}],
      sorts: [['newest', 'Сначала новые', (p, q) => q.id - p.id], ['title', 'По названию', (p, q) => p.title.localeCompare(q.title) || p.id - q.id],
        ['size', 'Сначала большие', (p, q) => q.size - p.size || p.id - q.id]],
      selected: () => current, clearSelection: () => { current = null; },
      empty: 'Документов пока нет', noResults: 'Документов с таким названием или видом нет.'});
    return h('div', {class: 'card stack'}, h('h3', {}, 'Документы'),
      h('p', {class: 'muted small'}, 'Исходные фотографии и файлы хранятся без изменений: значения, прочитанные с них, можно сверить с оригиналом.'),
      d.documents.length ? items.el : h('p', {class: 'muted'}, 'Документов пока нет'), DeviceForms.uploadForm(d, reload));
  }

  function capabilityResultsCard(results, deviceId) {
    const items = (results || []).map((r) => {
      const lens = r.lens ? App.lensLabel(r.lens) : 'линза не записана';
      const material = [r.material?.name, r.material?.grade, r.material?.batch && `партия ${r.material.batch}`].filter(Boolean).join(' · ') || 'титан не указан';
      return h('div', {class: 'card stack'},
        h('div', {class: 'row'}, link('/analysis/' + r.pair_id, r.test_name), h('span', {class: 'spacer'}), pill(`${r.measured_features} измерено`, 'ok')),
        h('p', {class: 'muted small'}, `${r.accepted_at ? r.accepted_at.slice(0, 10) + ' · ' : ''}${lens} · ${material}`),
        h('p', {}, r.finding),
        ...(r.use_cases || []).filter((item) => item.purpose === 'line' || item.purpose === 'text').map((item) =>
          h('p', {class: 'muted small'}, `${item.purpose === 'line' ? 'Линии' : 'Текст'}: ${item.summary}`)),
        link('/analysis/' + r.pair_id, 'Открыть полный разбор'));
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Результаты испытаний этого лазера'),
      h('p', {class: 'muted small'}, 'Здесь показываются принятые измерения тестовых плат. Каждый результат сохраняет свою линзу и заготовку титана; подробности и ограничения — в полном разборе.'),
      items.length ? items : h('div', {class: 'empty'}, h('p', {}, 'Принятых результатов тестовых плат пока нет.'), link('/experiments', 'Открыть экспериментальные платы')));
  }

  // The experiments of this laser are the one experiment list filtered by it (REQ-028): no list of plates, engravings or
  // photographs of its own; the same short list with the same search, filters and order as the experiments screen (DEC-090).
  // Beside it, the lookup of a measured result by its settings.
  function experimentsCard(experiments, device, lenses) {
    const byLens = new Map();
    for (const item of experiments) {          // the lens of each work is its lens record (lens_id), not a stored snapshot
      const key = item.lens_id == null ? '' : String(item.lens_id);
      const lens = lenses.find((l) => l.id === item.lens_id);
      if (!byLens.has(key)) byLens.set(key, lens ? App.lensLabel(lens) : 'Историческая линза неизвестна');
    }
    if (device.lens && !byLens.has(String(device.lens.id))) byLens.set(String(device.lens.id), `${App.lensLabel(device.lens)} (установлена сейчас)`);
    const lensPicker = h('select', {}, [...byLens].map(([id, label]) => h('option', {value: id}, label)));
    // the lookup compares exact settings: the server takes any number here (a whole one for the passes), so no end is told and no value is adjusted;
    // an empty or a non-number box is said beside it, and the other typed values stay (ux-save-feedback-p0, REQ-003)
    const lookup = Forms.create();
    const inputs = [['power', 'Мощность', 'lookupPower'], ['frequency', 'Частота', 'lookupFrequency'], ['speed', 'Скорость', 'lookupSpeed'],
      ['pulse_width', 'Импульс', 'lookupPulse'], ['line_interval', 'Шаг линий', 'lookupInterval'], ['passes', 'Проходы', 'lookupPasses']]
      .map(([key, label, quantity]) => lookup.add(key, label, Forms.numberInput(Forms.QUANTITIES[quantity]), {quantity, required: true}));
    const result = h('div', {});
    // REQ-020: результаты разных задач гравировки не смешиваются; можно искать только одну задачу
    const taskPicker = Tasks.select('', {empty: 'все задачи, каждая отдельно', aria: 'Задача гравировки'});
    const form = h('form', {class: 'stack', onsubmit: async (event) => {
      event.preventDefault();
      const values = lookup.collect();
      if (!values) return;
      try {
        const found = await post(`/devices/${device.id}/result-lookup`, {lens_id: lensPicker.value === '' ? null : +lensPicker.value, ...values,
          task: taskPicker.value || null});
        if (!found.matches.length) result.replaceChildren(h('div', {class: 'empty'}, h('p', {}, 'Для этой линзы и этих настроек принятых измерений пока нет.')));
        else {
          const cards = found.matches.map((m) => {
            const contexts = m.material_contexts.map((c) => h('p', {class: 'muted small'},
              `Титан: ${[c.titanium_name, c.titanium_grade, c.titanium_thickness_mm && `${c.titanium_thickness_mm} мм`, c.titanium_surface, c.batch && `партия ${c.batch}`].filter(Boolean).join(' · ') || 'не записан'} · фокус ${c.focus ?? 'не записан'} · ${c.observations} измерений`));
            const sources = m.source_pair_ids.map((pairId) => link('/analysis/' + pairId, `Фото/анализ пары ${pairId}`));
            return h('div', {class: 'card stack'},
              h('p', {}, `${labText(m.lab)} · ${m.available_for_prediction ? 'есть независимые повторы' : 'пока одно наблюдение; повторяемость не оценена'}`),
              h('p', {class: 'small'}, Tasks.badge(m.task), ` Измерено (не прогноз): наблюдений ${m.sample.observations} · независимых гравировок ${m.sample.independent_engravings}`
                + ` · фото ${m.sample.photographs}`, ...(m.missing_context.length ? [' · не хватает: ', ...Tasks.missing(m.missing_context)] : [])),
              h('p', {class: 'muted small'}, `Операция LightBurn: ${m.parameters.layer_type || 'режим не записан'} · глобальных проходов: ${m.parameters.global_passes ?? '—'} · дополнительные настройки сохранены в карточке результата.`),
              ...contexts, h('p', {class: 'muted small'}, `Уверенность: ${num(m.confidence)} · ожидаемая ошибка ΔE: ${num(m.expected_delta_e)}`),
              h('div', {class: 'row'}, ...sources));
          });
          result.replaceChildren(h('div', {class: 'stack'}, h('h4', {}, `Найдено сочетаний режима и титана: ${found.matches.length}`), ...cards));
        }
      } catch (error) { lookup.fail(error); }
    }},
      h('div', {class: 'grid g3'}, field('Историческая линза', lensPicker), ...inputs, field('Задача', taskPicker)),
      lookup.error, h('button', {type: 'submit', class: 'btn primary'}, 'Найти измеренный результат'), result);

    return h('div', {class: 'stack'}, h('div', {class: 'card stack'}, h('h3', {}, 'База измерений: параметры → результат'),
      h('p', {class: 'muted small'}, 'Поиск измеренного результата по шести основным настройкам. Только принятые измерения используются для подбора; каждое ведёт к своему эксперименту.'), form),
      h('section', {class: 'card dashboard-panel'},
        h('div', {class: 'dashboard-panel-head'}, h('h3', {}, 'Эксперименты этого лазера'), pill(experiments.length),
          link('/experiments?device=' + device.id, 'Открыть в общем списке')),
        experiments.length ? ExperimentCards.list(experiments, {id: 'laser-experiments', empty: 'Ничего не найдено: измените поиск, состояние или задачу.'})
          : h('div', {class: 'empty'}, h('p', {}, 'Экспериментов для этого лазера пока нет.'), link('/experiments', 'Создать эксперимент'))));
  }
  return {passportCard, stepsCard, documentsCard, capabilityResultsCard, experimentsCard, g};
})();
