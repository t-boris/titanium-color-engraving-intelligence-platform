/* Анализ принятой гравировки: обзор измерений с подробностями по требованию. */
'use strict';
(() => {
  const {h, btn, link, pill, get, post, del, go, toast, fail, confirmBox, modal, num, labText, swatch} = App;
  const MODE = {'Calibration plate': 'Калибровочная плата', 'Laser capability test': 'Тест возможностей лазера',
    'Discrete color engraving': 'Цветная гравировка', 'Tonal photo engraving': 'Тональная фотогравировка',
    'Color-path photo engraving': 'Фотогравировка по цветовому пути'};
  const PURPOSE = {line: 'Линии', text: 'Текст', color: 'Цвет', image: 'Изображение'};
  const PURPOSE_STATUS = {candidate: ['Кандидат', 'ok'], incomplete_settings: ['Не хватает настроек', 'warn'],
    insufficient: ['Недостаточно данных', 'warn'], needs_text_test: ['Нужен тест', 'warn'],
    needs_color_test: ['Нужен тест', 'warn'], needs_image_test: ['Нужен тест', 'warn'],
    contrast_candidate: ['Контрастный образец', 'warn']};
  const GROUPS = [
    ['gap', 'Разнос линий'], ['frequency', 'Частота'], ['wobble', 'Wobble'],
    ['hatch', 'Шаг заливки'], ['text', 'Текст'], ['surface', 'Очистка и метки'], ['other', 'Другие элементы']];
  const LAYER_TYPE = {Cut: 'Линия', Scan: 'Заливка', OffsetFill: 'Смещённая заливка', Image: 'Изображение'};
  const SOURCE_LABELS = {maxPower: 'Макс. мощность', maxPower2: 'Вторая мощность', speed: 'Скорость',
    frequency: 'Частота (Гц)', QPulseWidth: 'Q-Pulse (нс)', interval: 'Интервал линий (мм)',
    numPasses: 'Проходы слоя', globalRepeat: 'Глобальные проходы', bidir: 'Двунаправленно',
    crossHatch: 'Перекрёстная заливка', angle: 'Угол сканирования', anglePerPass: 'Приращение угла',
    wobbleEnable: 'Wobble включён', wobbleStep: 'Wobble шаг (мм)', wobbleSize: 'Wobble размер (мм)',
    priority: 'Порядок слоя', tabCount: 'Количество выступов', tabCountMax: 'Макс. выступов'};

  const kpi = (value, label, hint = '') => h('div', {class: 'analysis-kpi', title: hint},
    h('strong', {}, value), h('span', {}, label));
  const card = (title, body, extraClass = '') => h('section', {class: 'card analysis-panel ' + extraClass},
    h('h3', {}, title), body);
  const unique = (items) => [...new Set(items.filter(Boolean))];
  const firstSentence = (value) => (value || '').split(/(?<=[.!?])\s/)[0];

  function settingsLabel(s = {}) {
    const parts = [];
    const source = s.source_settings || {};
    const setting = (name) => source[name]?.Value;
    parts.push(LAYER_TYPE[s.layer_type] || s.layer_type || 'Режим не указан');
    if (s.power != null) parts.push(`${num(s.power, 1)} %`);
    if (s.frequency != null) parts.push(`${num(s.frequency, 1)} кГц`);
    if (s.speed != null) parts.push(`${num(s.speed, 0)} мм/с`);
    parts.push(s.pulse_width != null ? `Q-Pulse ${num(s.pulse_width, 0)} нс` : 'Q-Pulse нет в файле');
    if (s.layer_type !== 'Cut' && s.line_interval != null) parts.push(`шаг ${num(s.line_interval, 4)} мм`);
    if (s.passes != null) parts.push(`${s.passes} проход(а)${!source.numPasses ? ' (по умолчанию)' : ''}`);
    if (s.global_passes != null) parts.push(`глобальных проходов ${s.global_passes}${!source.globalRepeat ? ' (по умолчанию)' : ''}`);
    if (s.layer_type !== 'Cut') {
      parts.push(`направление: ${s.bidirectional ? 'двунаправленно' : 'однонаправленно'}${!source.bidir ? ' (по умолчанию)' : ''}`);
      parts.push(`угол ${num(s.scan_angle ?? 0, 1)}°${!source.angle ? ' (по умолчанию)' : ''}`);
      parts.push(`приращение угла ${num(s.angle_increment ?? 0, 1)}°${!source.anglePerPass ? ' (по умолчанию)' : ''}`);
      parts.push(`перекрёстная заливка ${s.cross_hatch ? 'да' : 'нет'}${!source.crossHatch ? ' (по умолчанию)' : ''}`);
    }
    if (setting('wobbleEnable') === '1') parts.push(setting('wobbleStep') != null && setting('wobbleSize') != null
      ? `Wobble: шаг ${setting('wobbleStep')} мм · размер ${setting('wobbleSize')} мм`
      : 'Wobble включён; шаг/размер не записаны в файле');
    return parts.join(' · ') || 'Параметры в файле не указаны';
  }

  function allSettings(s = {}) {
    const source = s.source_settings || {};
    const sourced = (tag, value) => source[tag] ? value : `${value} · по умолчанию, в файле нет`;
    const wobble = source.wobbleEnable?.Value;
    const normalized = [
      ['Режим', LAYER_TYPE[s.layer_type] || s.layer_type || 'нет в файле'],
      ['Мощность', s.power == null ? 'нет в файле' : `${num(s.power, 2)} %`],
      ['Частота', s.frequency == null ? 'нет в файле' : `${num(s.frequency, 2)} кГц`],
      ['Скорость', s.speed == null ? 'нет в файле' : `${num(s.speed, 2)} мм/с`],
      ['Q-Pulse', s.pulse_width == null ? 'нет в файле' : `${num(s.pulse_width, 2)} нс`],
      ['Интервал линий', s.layer_type === 'Cut' ? 'не применяется к линии' : s.line_interval == null ? 'нет в файле' : `${num(s.line_interval, 4)} мм`],
      ['Проходы слоя', s.passes == null ? 'нет в файле' : sourced('numPasses', String(s.passes))],
      ['Глобальные проходы', s.global_passes == null ? 'нет в файле' : sourced('globalRepeat', String(s.global_passes))],
      ['Направление прохода', s.bidirectional == null ? 'нет в файле' : sourced('bidir', s.bidirectional ? 'двунаправленно' : 'однонаправленно')],
      ['Перекрёстная заливка', s.cross_hatch == null ? 'нет в файле' : sourced('crossHatch', s.cross_hatch ? 'да' : 'нет')],
      ['Угол сканирования', s.scan_angle == null ? 'нет в файле' : sourced('angle', `${num(s.scan_angle, 2)}°`)],
      ['Приращение угла', s.angle_increment == null ? 'нет в файле' : sourced('anglePerPass', `${num(s.angle_increment, 2)}°`)],
      ['Wobble', source.wobbleEnable ? ['1', 'true', 'yes'].includes(String(wobble).toLowerCase()) ? 'включён' : 'выключен' : 'нет записи в файле'],
      ['Wobble: шаг', source.wobbleStep?.Value == null ? 'нет в файле' : `${source.wobbleStep.Value} мм`],
      ['Wobble: размер', source.wobbleSize?.Value == null ? 'нет в файле' : `${source.wobbleSize.Value} мм`],
    ];
    return h('div', {class: 'analysis-settings'},
      h('strong', {}, 'Прочитанные параметры слоя'),
      h('div', {class: 'analysis-settings-grid'}, ...normalized.map(([label, value]) => h('div', {}, h('span', {}, label), h('b', {}, value)))),
      h('details', {}, h('summary', {}, `Все поля LightBurn в этом слое (${Object.keys(source).length})`),
        h('div', {class: 'analysis-source-grid'}, ...Object.entries(source).map(([tag, raw]) => {
          const value = raw && typeof raw === 'object' && Object.keys(raw).length === 1 && raw.Value != null
            ? raw.Value : typeof raw === 'string' ? raw : JSON.stringify(raw);
          return h('div', {}, h('span', {}, SOURCE_LABELS[tag] || tag), h('code', {}, `${tag} = ${value}`));
        }))));
  }

  function groupOf(row) {
    const name = row.name || '';
    if (name.startsWith('LINE-GAP-')) return 'gap';
    if (name.startsWith('FREQUENCY-')) return 'frequency';
    if (name.startsWith('WOBBLE-')) return 'wobble';
    if (name.startsWith('HATCH-')) return 'hatch';
    if (name.startsWith('TEXT-')) return 'text';
    if (row.role === 'pre-test cleaning witness' || row.role === 'registration, QR and engraved labels') return 'surface';
    return 'other';
  }

  function detailBody(row, capability) {
    const m = row.line_metrics;
    const measurements = [];
    if (m) {
      measurements.push(kpi(`${m.visible_line_count}/${m.line_count}`, 'различимых линий'));
      if (m.median_continuity_percent != null) measurements.push(kpi(`${num(m.median_continuity_percent, 0)}%`, 'непрерывность'));
      if (m.median_contrast_Lstar != null) measurements.push(kpi(num(m.median_contrast_Lstar, 1), 'контраст L*'));
      if (m.median_apparent_trace_width_mm != null) measurements.push(kpi(`${num(m.median_apparent_trace_width_mm, 3)} мм`, 'видимая ширина следа', 'Не диаметр оптического пятна'));
    }
    return h('div', {class: 'analysis-detail-body'},
      allSettings(row.parameters),
      measurements.length ? h('div', {class: 'analysis-detail-kpis'}, ...measurements) : null,
      row.measured_lab_against_clean ? h('p', {class: 'analysis-lab'}, swatch(row.measured_lab_against_clean),
        `Цвет относительно чистого титана: ${labText(row.measured_lab_against_clean)}`, h('span', {class: 'muted small'}, ` · как снято: ${labText(row.measured_lab)}`))
      : row.measured_lab ? h('p', {class: 'analysis-lab'}, swatch(row.measured_lab),
        `${capability ? 'Отклик камеры' : 'Измеренный цвет'}: ${labText(row.measured_lab)}`) : h('p', {class: 'muted small'}, 'На фото не измерено'),
      row.planned_lab ? h('p', {class: 'small'}, 'Плановый цвет: ', swatch(row.planned_lab), labText(row.planned_lab),
        row.delta_e != null ? ` · ΔE ${num(row.delta_e, 1)}` : '') : null,
      row.note ? h('p', {class: 'muted small'}, I18N.tr(row.note)) : null,
      row.name?.startsWith('TEXT-') ? h('p', {class: 'alert warn small'}, 'Измерен отклик надписи на фотографии. Контраст сам по себе не подтверждает читаемость символов и качество кромки.') : null,
      row.name?.startsWith('WOBBLE-') ? h('p', {class: 'alert warn small'}, 'Измерен отклик участка; геометрия дорожки пока не оценена.') : null,
      m?.groups?.length ? h('div', {class: 'analysis-sublist'},
        h('strong', {}, 'Группы зазоров'), ...m.groups.map((g) => h('div', {},
          `${g.spacing_um} мкм · ${g.visible_line_count}/${g.line_count} линий · непрерывность ${num(g.median_continuity_percent, 0)}%`))) : null,
      row.submeasurements?.length ? h('div', {class: 'analysis-sublist'},
        h('strong', {}, `Отдельные элементы (${row.submeasurements.length})`),
        ...row.submeasurements.map((item) => h('div', {}, item.name, ' · ', item.measured_lab ? labText(item.measured_lab) : 'не измерен'))) : null);
  }

  function showElement(row, capability) {
    modal(row.name || `Слой ${row.layer_index}`, detailBody(row, capability),
      [{label: 'Закрыть', run: ({close}) => close()}]);
  }
  function showGroup(title, rows, capability) {
    const body = h('div', {class: 'analysis-detail-list'},
      ...rows.map((row) => h('details', {class: 'analysis-detail-item'},
        h('summary', {}, h('strong', {}, row.name || `Слой ${row.layer_index}`),
          row.line_metrics ? h('span', {class: 'muted small'}, `${row.line_metrics.visible_line_count}/${row.line_metrics.line_count} линий`) :
            row.measured_lab ? h('span', {class: 'muted small'}, `L* ${num((row.measured_lab_against_clean || row.measured_lab)[0], 1)}`) : null),
        detailBody(row, capability))));
    modal(title, body, [{label: 'Закрыть', run: ({close}) => close()}]);
  }

  function useCases(c) {
    return h('div', {class: 'analysis-use-list'}, ...(c.use_cases || []).map((item) => {
      const [status, kind] = PURPOSE_STATUS[item.status] || [item.status, 'warn'];
      return h('button', {type: 'button', class: 'analysis-use', onClick: () => modal(PURPOSE[item.purpose] || item.purpose,
        h('div', {class: 'stack'}, h('p', {}, item.summary),
          item.parameters ? h('p', {class: 'analysis-params'}, settingsLabel(item.parameters)) : null,
          h('div', {class: 'alert'}, h('strong', {}, 'Следующий шаг'), h('p', {}, item.next_test)),
          item.evidence?.name ? h('p', {class: 'muted small'}, `Основание: ${item.evidence.name}`) : null),
        [{label: 'Закрыть', run: ({close}) => close()}])},
        h('span', {class: 'analysis-use-top'}, h('strong', {}, PURPOSE[item.purpose] || item.purpose), pill(status, kind)),
        h('span', {class: 'analysis-use-preview'}, firstSentence(item.summary)));
    }));
  }

  function matrix(rows) {
    const lineRows = rows.filter((row) => row.name?.startsWith('LINE-P'));
    if (!lineRows.length) return h('p', {class: 'muted'}, 'Матрица одиночных линий в этом файле отсутствует.');
    const powers = unique(lineRows.map((row) => row.parameters?.power)).sort((a, b) => a - b);
    const speeds = unique(lineRows.map((row) => row.parameters?.speed)).sort((a, b) => a - b);
    const byCell = new Map(lineRows.map((row) => [`${row.parameters.power}/${row.parameters.speed}`, row]));
    return h('div', {class: 'analysis-matrix-wrap'},
      h('p', {class: 'muted small'}, 'Столбцы — мощность (%), строки — скорость (мм/с). Нажмите ячейку для параметров и измерений.'),
      h('div', {class: 'analysis-matrix', style: `--axis-columns:${powers.length}`},
        h('span', {class: 'analysis-axis'}, 'V / P'),
        ...powers.map((power) => h('strong', {class: 'analysis-axis'}, `${power}%`)),
        ...speeds.flatMap((speed) => [h('strong', {class: 'analysis-axis'}, speed), ...powers.map((power) => {
          const row = byCell.get(`${power}/${speed}`);
          const m = row?.line_metrics;
          const visible = (m?.visible_line_count || 0) > 0;
          const strong = visible && (m?.median_continuity_percent || 0) >= 90;
          const status = !row ? 'unknown' : strong ? 'strong' : visible ? 'partial' : 'absent';
          return h('button', {type: 'button', class: `analysis-cell ${status}`, disabled: !row,
            title: row ? `${row.name} · ${settingsLabel(row.parameters)}` : 'Нет элемента',
            'aria-label': `${power}% · ${speed} мм/с · ${strong ? 'непрерывная линия' : visible ? 'частичный след' : 'линия не подтверждена'}`,
            onClick: () => showElement(row, true)}, row ? visible ? `${num(m.median_continuity_percent, 0)}%` : '—' : '');
        })])),
      h('div', {class: 'analysis-legend'},
        h('span', {}, h('i', {class: 'strong'}, ''), 'Непрерывная'),
        h('span', {}, h('i', {class: 'partial'}, ''), 'Частичная'),
        h('span', {}, h('i', {class: 'absent'}, ''), 'Не подтверждена')));
  }

  function groupSummary(id, rows) {
    if (id === 'gap') {
      const m = rows[0]?.line_metrics;
      return m ? `${m.visible_line_count}/${m.line_count} линий · ${m.groups?.length || 0} расстояний` : 'Зазоры измерены';
    }
    if (id === 'frequency') {
      const visible = rows.filter((row) => row.line_metrics?.visible_line_count).length;
      const best = rows.reduce((top, row) => !top || (row.line_metrics?.median_continuity_percent || 0) >
        (top.line_metrics?.median_continuity_percent || 0) ? row : top, null);
      return `${visible}/${rows.length} линий видны${best ? ` · максимум ${num(best.line_metrics?.median_continuity_percent, 0)}%` : ''}`;
    }
    if (id === 'text') return `${rows.flatMap((row) => row.submeasurements || []).length || rows.length} размеров · читаемость не оценена`;
    const lightness = rows.filter((row) => row.measured_lab).map((row) => row.measured_lab[0]);
    return lightness.length ? `${rows.length} участка · L* ${num(Math.min(...lightness), 1)}–${num(Math.max(...lightness), 1)}` : `${rows.length} элемента`;
  }

  function capabilityDashboard(r) {
    const c = r.capability;
    const groups = new Map();
    for (const row of r.rows) {
      if (row.name?.startsWith('LINE-P')) continue;
      const group = groupOf(row);
      if (!groups.has(group)) groups.set(group, []);
      groups.get(group).push(row);
    }
    const modules = GROUPS.filter(([id]) => groups.has(id)).map(([id, title]) => {
      const rows = groups.get(id);
      return h('button', {type: 'button', class: 'analysis-module', onClick: () => showGroup(title, rows, true)},
        h('strong', {}, title), h('span', {}, groupSummary(id, rows)), h('small', {}, `Элементов: ${rows.length} · открыть измерения →`));
    });
    const limitations = unique([...(r.limitations || []).map((text) => I18N.tr(text)), ...(c.limitations || [])]);
    const lightness = c.lightness_range ? `${num(c.lightness_range[0], 1)}–${num(c.lightness_range[1], 1)}` : '—';
    return [
      h('div', {class: 'analysis-kpi-grid'}, kpi(c.measured_features, 'тестовых слоёв'),
        kpi(`${c.line_response?.visible || 0}/${c.line_response?.tested || 0}`, 'одиночных линий видны'),
        kpi(c.gap_response ? `${c.gap_response.visible_line_count}/${c.gap_response.line_count}` : '—', 'линий в группах зазоров'),
        kpi(lightness, 'диапазон L* на RAW')),
      h('div', {class: 'analysis-primary'},
        card('Мощность × скорость', matrix(r.rows)),
        card('Выводы по задачам', useCases(c))),
      h('div', {class: 'analysis-modules'}, ...modules),
      h('div', {class: 'analysis-bottom'},
        card('Что показала фотография', h('div', {class: 'analysis-conclusions'},
          h('p', {class: 'analysis-lead'}, c.finding),
          ...(c.signals || []).slice(0, 2).map((signal) => h('p', {}, signal)),
          (c.signals || []).length > 2 ? btn(`Все наблюдения (${c.signals.length})`, () => modal('Наблюдения по фотографии',
            h('div', {class: 'analysis-detail-list'}, ...c.signals.map((signal) => h('p', {}, signal))),
            [{label: 'Закрыть', run: ({close}) => close()}]), 'btn-small') : null)),
        card('Что сделать дальше', h('div', {class: 'analysis-conclusions'},
          ...(c.next_steps || []).slice(0, 2).map((step, i) => h('p', {}, h('strong', {}, `${i + 1}. `), step)),
          (c.next_steps || []).length > 2 ? btn(`Все шаги (${c.next_steps.length})`, () => modal('Следующие проверки',
            h('div', {class: 'analysis-detail-list'}, ...c.next_steps.map((step, i) => h('p', {}, `${i + 1}. ${step}`))),
            [{label: 'Закрыть', run: ({close}) => close()}]), 'btn-small') : null))),
      h('details', {class: 'analysis-footnote'}, h('summary', {}, `Ограничения измерений (${limitations.length})`),
        ...limitations.map((text) => h('p', {}, text)))
    ];
  }

  function genericDashboard(r) {
    const m = r.metrics || {};
    let values;
    if (m.kind === 'brightness_contrast') values = [[m.bands, 'полос'], [num(m.measured_contrast, 1), 'измеренный ΔL'],
      [num(m.planned_contrast, 1), 'плановый ΔL'], [m.monotonic ? 'Да' : 'Нет', 'монотонность']];
    else if (m.kind === 'delta_e_along_path') values = [[m.bands, 'полос'], [num(m.mean_delta_e, 1), 'средний ΔE'],
      [num(m.max_delta_e, 1), 'максимальный ΔE'], [num(m.mean_path_distance, 1), 'отклонение от пути']];
    else if (m.kind === 'color_deviation') values = [[m.layers, 'слоёв'], [num(m.mean_delta_e, 1), 'средний ΔE'],
      [num(m.max_delta_e, 1), 'максимальный ΔE'], [r.tolerance == null ? '—' : num(r.tolerance, 1), 'допуск ΔE']];
    else values = [[r.rows.length, 'измеренных слоёв'], [r.photos?.length || 1, 'фото запуска'],
      [r.rows.filter((row) => row.measured_lab).length, 'участков с цветом'], ['—', 'плановый цвет']];
    const layers = r.rows.map((row) => h('button', {type: 'button', class: 'analysis-module', onClick: () => showElement(row, false)},
      h('strong', {}, row.name || `Слой ${row.layer_index}`),
      h('span', {}, row.measured_lab ? [swatch(row.measured_lab_against_clean || row.measured_lab), labText(row.measured_lab_against_clean || row.measured_lab)] : 'На фото не измерено'),
      h('small', {}, settingsLabel(row.parameters))));
    const ref = r.clean_reference;
    return [h('div', {class: 'analysis-kpi-grid'}, ...values.map(([value, label]) => kpi(value, label))),
      ...(ref ? [h('div', {class: 'alert ok', role: 'status'},
        `Цвета приведены к чистому титану этой же фотографии: слой очистки снят как L* ${num(ref.lab[0], 1)} и принят за L* ${num(ref.nominal[0], 0)}`
        + `${ref.nominal_source === 'chart' ? ' (по измерениям с картой)' : ' (значение по умолчанию)'}`
        + (Math.abs(ref.exposure_stops) >= 1 ? `; снимок ${ref.exposure_stops > 0 ? 'темнее' : 'светлее'} номинала на ${num(Math.abs(ref.exposure_stops), 1)} ступени экспозиции` : '')
        + '. Отношение цвета к чистому титану в линейном свете от экспозиции не зависит; значение «как снято» сохранено как свидетельство.')] : []),
      card('Измеренные элементы', h('div', {class: 'analysis-modules'}, ...layers)),
      r.limitations?.length ? h('details', {class: 'analysis-footnote'}, h('summary', {}, `Ограничения измерений (${r.limitations.length})`),
        ...r.limitations.map((text) => h('p', {}, I18N.tr(text)))) : null];
  }

  App.register({id: 'analysis', async render(ctx) {
    const id = ctx.arg;
    let r;
    try { r = await get(`/pairs/${id}/report`); }
    catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Отчёт не найден'), h('p', {}, e.message), link('/experiments', 'К экспериментам')); }
    const c = r.capability;
    const material = c ? [c.material?.name, c.material?.grade, c.material?.batch].filter(Boolean).join(' · ') : '';
    const device = c?.device?.name;
    const lens = c?.lens?.name;
    const align = {'markers': 'по маркерам', 'marker templates': 'по узорам маркеров', manual: 'вручную',
      'manual shift': 'сдвиг вручную', 'manual rotation': 'поворот вручную', 'manual transform': 'масштаб или зеркало',
      'element anchor': 'по детали', 'element anchors': 'по элементам-якорям', picture: 'по вложенной картинке', geometry: 'по деталям рисунка',
      'single distinctive detail': 'по одной характерной детали', 'two marker + QR': 'по двум меткам и QR'}[r.alignment] || 'не указано';
    const revise = btn('Исправить совмещение', async (ev) => {
      const control = ev.currentTarget; control.disabled = true; control.textContent = 'Создаём исправление…';
      try { const revision = await post(`/pairs/${id}/alignment-revisions`);
        toast('Создано исправление по тому же RAW; прежние измерения сохраняются до принятия новых', 'ok');
        go('/ingest?pair=' + revision.id);
      } catch (error) { control.disabled = false; control.textContent = 'Исправить совмещение'; fail(error); }
    }, 'btn-small');
    const remove = btn('Удалить проверку', () => confirmBox('Удалить проверку',
      'Фотография и её измерения исчезнут из активной базы. История измерений останется для аудита; другие проверки гравировки сохранятся.',
      'Удалить', async () => { await del(`/pairs/${id}`); toast('Проверка удалена', 'ok'); go('/experiments'); }), 'btn-small danger');
    return h('div', {class: 'analysis-dashboard'},
      h('div', {class: 'analysis-hero'},
        h('div', {}, h('h2', {}, r.engraving_title || 'Анализ гравировки'),
          h('p', {class: 'sub'}, [MODE[r.mode] || 'Гравировка', device, lens, material].filter(Boolean).join(' · ')),
          h('p', {class: 'muted small'}, `Проверка №${id} · совмещение ${align}${c?.measurement_modes?.includes('raw_camera_relative') ? ' · RAW без эталонной карты' : ''}`)),
        h('div', {class: 'analysis-actions'}, link('/experiment/' + (r.plan_id ? 'plan-' + r.plan_id : 'eng-' + r.engraving_id), 'К эксперименту'),
          r.plan_id ? link('/plans/' + r.plan_id, 'Плата') : null,
          link('/ingest?rephoto=' + id, '+ Фото'), revise, remove)),
      r.photos?.length > 1 ? h('div', {class: 'analysis-photo-strip'},
        h('span', {}, `Проверки этого запуска (${r.photos.length})`),
        ...r.photos.map((photo) => link(photo.status === 'Accepted' ? '/analysis/' + photo.id : '/ingest?pair=' + photo.id,
          `№${photo.id} · ${photo.photo_name}${photo.id === Number(id) ? ' · сейчас' : ''}`))) : null,
      ...(c ? capabilityDashboard(r) : genericDashboard(r)));
  }});
})();
