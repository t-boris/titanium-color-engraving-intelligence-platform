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
        ['Наибольшая энергия импульса', p.max_pulse_energy_mj ? p.max_pulse_energy_mj + ' мДж' : null],
        ['Диаметр пятна на металле', p.spot_diameter_um ? p.spot_diameter_um + ' мкм' : 'не задан: плотность энергии не считается']]),
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

  function documentsCard(d, reload) {
    const items = d.documents.map((x) => {
      const url = `/api/devices/${d.id}/documents/${x.id}`;
      const preview = x.media_type.startsWith('image/')
        ? h('a', {href: url, target: '_blank', rel: 'noopener'}, h('img', {src: url, alt: x.title, loading: 'lazy', style: 'max-width:220px;max-height:160px;object-fit:cover'})) : null;
      return h('div', {class: 'card stack', style: 'min-width:0'}, preview, h('strong', {}, x.title),
        h('p', {class: 'muted small'}, `${DeviceForms.KIND[x.kind] || x.kind} · ${x.filename} · ${size(x.size)}`),
        h('div', {class: 'row'}, h('a', {href: url, target: '_blank', rel: 'noopener'}, 'Открыть'),
          btn('Удалить', () => confirmBox('Удалить документ', `«${x.title}». Файл будет удалён с диска, паспорт останется.`, 'Удалить',
            async () => { await del(`/devices/${d.id}/documents/${x.id}`); toast('Документ удалён', 'ok'); reload(d.id); }), 'danger')));
    });
    return h('div', {class: 'card stack'}, h('h3', {}, 'Документы'),
      h('p', {class: 'muted small'}, 'Исходные фотографии и файлы хранятся без изменений: значения, прочитанные с них, можно сверить с оригиналом.'),
      items.length ? h('div', {class: 'grid g3'}, items) : h('p', {class: 'muted'}, 'Документов пока нет'), DeviceForms.uploadForm(d, reload));
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
  // photographs of its own. Beside it, the lookup of a measured result by its settings.
  function experimentsCard(experiments, device, lenses) {
    const byLens = new Map();
    for (const item of experiments) {          // the lens of each work is its lens record (lens_id), not a stored snapshot
      const key = item.lens_id == null ? '' : String(item.lens_id);
      const lens = lenses.find((l) => l.id === item.lens_id);
      if (!byLens.has(key)) byLens.set(key, lens ? App.lensLabel(lens) : 'Историческая линза неизвестна');
    }
    if (device.lens && !byLens.has(String(device.lens.id))) byLens.set(String(device.lens.id), `${App.lensLabel(device.lens)} (установлена сейчас)`);
    const lensPicker = h('select', {}, [...byLens].map(([id, label]) => h('option', {value: id}, label)));
    const inputs = [
      ['Мощность, %', 'power', '0.1'], ['Частота, кГц', 'frequency', '1'], ['Скорость, мм/с', 'speed', '1'],
      ['Импульс, нс', 'pulse_width', '1'], ['Шаг линий, мм', 'line_interval', '0.001'], ['Проходы', 'passes', '1'],
    ].map(([label, key, step]) => [key, field(label, h('input', {type: 'number', min: key === 'passes' ? 1 : 0, step, required: true}))]);
    const result = h('div', {});
    // REQ-020: результаты разных задач гравировки не смешиваются; можно искать только одну задачу
    const taskPicker = Tasks.select('', {empty: 'все задачи, каждая отдельно', aria: 'Задача гравировки'});
    const form = h('form', {class: 'stack', onsubmit: async (event) => {
      event.preventDefault();
      const values = Object.fromEntries(inputs.map(([key, control]) => [key, +control.querySelector('input').value]));
      if (inputs.some(([, control]) => control.querySelector('input').value === '')) return fail('Заполните все шесть параметров.');
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
      } catch (error) { fail(error); }
    }},
      h('div', {class: 'grid g3'}, field('Историческая линза', lensPicker), ...inputs.map(([, control]) => control), field('Задача', taskPicker)),
      h('button', {type: 'submit', class: 'btn primary'}, 'Найти измеренный результат'), result);

    return h('div', {class: 'stack'}, h('div', {class: 'card stack'}, h('h3', {}, 'База измерений: параметры → результат'),
      h('p', {class: 'muted small'}, 'Поиск измеренного результата по шести основным настройкам. Только принятые измерения используются для подбора; каждое ведёт к своему эксперименту.'), form),
      h('section', {class: 'card dashboard-panel'},
        h('div', {class: 'dashboard-panel-head'}, h('h3', {}, 'Эксперименты этого лазера'), pill(experiments.length),
          link('/experiments?device=' + device.id, 'Открыть в общем списке')),
        experiments.length ? ExperimentCards.list(experiments, '')
          : h('div', {class: 'empty'}, h('p', {}, 'Экспериментов для этого лазера пока нет.'), link('/experiments', 'Создать эксперимент'))));
  }
  return {passportCard, stepsCard, documentsCard, capabilityResultsCard, experimentsCard, g};
})();
