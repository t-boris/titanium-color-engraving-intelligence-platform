/* Эксперименты одним списком: каждый открывается целиком (плата, фото с наложением, результат); рядом выводы для материала (REQ-028). */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, toast} = App;
  const KIND = {'Awaiting check': ['Ожидает проверки', ''], 'Needs correction': ['Требует исправления', 'warn'],
    'Ready to accept': ['Готова к принятию', 'ok'], Accepted: ['Принята', 'ok']};
  const MODE = {'Calibration plate': 'Калибровочная матрица', 'Laser capability test': 'Тест возможностей лазера',
    'Discrete color engraving': 'Цветная гравировка', 'Tonal photo engraving': 'Тональная фотогравировка',
    'Color-path photo engraving': 'Фотогравировка по цветовому пути', 'Restored from file': 'Восстановленный из файла'};
  const PURPOSE = {line: 'Линии', text: 'Текст', color: 'Цвет', image: 'Изображение'};
  const PLATE_TYPE = {text_readability: 'надписи 3 × 3, три размера', material_matrix: 'матрица 3 × 3', compact_capability: 'компактная комплексная проверка',
    calibration: 'калибровочная матрица', hatch_interval: 'шаг заливки'};
  const settingSummary = (p) => p ? [
    p.power == null ? null : `${p.power}%`, p.frequency == null ? null : `${p.frequency} кГц`,
    p.speed == null ? null : `${p.speed} мм/с`,
    `Q-Pulse ${p.pulse_width == null ? 'не записан' : p.pulse_width + ' нс'}`,
    p.line_interval == null ? null : `шаг ${p.line_interval} мм`,
    p.passes == null ? null : `${p.passes} проход(а)`,
    p.global_passes == null ? null : `глобально ${p.global_passes}×`,
    p.scan_angle == null ? null : `угол ${p.scan_angle}°`,
    p.angle_increment == null ? null : `приращение ${p.angle_increment}°`,
    p.bidirectional == null ? null : `двунаправленно ${p.bidirectional ? 'да' : 'нет'}`,
    p.cross_hatch == null ? null : `перекрёстная заливка ${p.cross_hatch ? 'да' : 'нет'}`,
    p.source_settings?.wobbleEnable?.Value === '1'
      ? `Wobble: размер ${p.source_settings.wobbleSize?.Value ?? '—'} мм, шаг ${p.source_settings.wobbleStep?.Value ?? '—'} мм` : null,
  ].filter(Boolean).join(' · ') : null;
  const checks = (n) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'проверка' :
    n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'проверки' : 'проверок'}`;
  const stat = (value, label, kind = '') => h('div', {class: `dashboard-stat ${kind}`}, h('strong', {}, value), h('span', {}, label));
  const panel = (title, count, items, empty, action) => h('section', {class: 'card dashboard-panel'},
    h('div', {class: 'dashboard-panel-head'}, h('h3', {}, title), pill(count), action),
    items.length ? h('div', {class: 'dashboard-list'}, ...items) : h('p', {class: 'muted small'}, empty));

  App.register({id: 'experiments', async render(ctx) {
    const [experiments, devices, materials, goals] = await Promise.all([
      get('/experiments'), get('/devices'), get('/materials'), get('/application-goals')]);
    const rememberedDevice = Number(sessionStorage.getItem('experiment-dashboard-device'));
    const selectedDevice = devices.find((device) => device.id === rememberedDevice) || devices[0];
    const rememberedMaterial = Number(sessionStorage.getItem('experiment-dashboard-material'));
    const selectedMaterial = materials.find((material) => material.id === rememberedMaterial) || materials[0];
    const selectedGoal = goals.find((goal) => goal.id === sessionStorage.getItem('experiment-dashboard-goal')) || goals[0];
    let findings = [];
    if (selectedDevice) {
      try { findings = await get(`/devices/${selectedDevice.id}/findings`); } catch (_) { /* Остальной обзор доступен. */ }
    }
    findings = findings.filter((finding) => finding.material_id === selectedMaterial?.id &&
      finding.lens_id === selectedDevice?.lens?.id);
    let guide = null;
    if (selectedDevice && selectedMaterial && selectedGoal) {
      try { guide = await get(`/application-guide?device_id=${selectedDevice.id}&material_id=${selectedMaterial.id}&goal=${selectedGoal.id}`); }
      catch (error) { guide = {status: 'error', message: error.message, next_step: 'Проверьте материал и параметры лазера.'}; }
    }
    const latest = new Map();
    for (const finding of findings) if (!latest.has(finding.purpose)) latest.set(finding.purpose, finding);
    const reload = () => App.render({preserveScroll: true});
    const hero = h('div', {class: 'dashboard-hero'},
      h('div', {}, h('h2', {}, 'Эксперименты'), h('p', {class: 'sub'}, 'Каждый эксперимент открывается целиком: плата, фото с наложением, результат')),
      h('div', {class: 'dashboard-actions'},
        link('/research', 'AI-исследователь'),
        link('/colors', 'Карта цветов'),
        btn('Создать плату', () => PlateDialog.open(devices, materials, reload), 'primary', !devices.length),
        link('/ingest', 'Добавить работу и фото')));
    if (!devices.length) return h('div', {class: 'stack'}, hero,
      h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер и установите линзу'), link('/devices', 'Лазеры')));

    const query = sessionStorage.getItem('experiment-search') || '';
    const wantedStatus = sessionStorage.getItem('experiment-status') || 'all';
    const wantedTask = sessionStorage.getItem('experiment-task') || '';      // REQ-020: эксперименты одной задачи гравировки
    // ?device=<id>: the experiments of one laser, the list its page links to (no separate list there)
    const laser = devices.find((device) => String(device.id) === String(ctx.query.device)) || null;
    const shown = experiments.filter((e) => (wantedStatus === 'all' || e.status === wantedStatus) && (!laser || e.device_id === laser.id) &&
      (!wantedTask || (e.tasks || []).includes(wantedTask)) &&
      (!query || [e.title, e.kind, e.laser, e.lens, e.material].filter(Boolean).join(' ').toLowerCase().includes(query.toLowerCase())));
    const filters = h('div', {class: 'row exp-filters'},
      laser ? h('span', {class: 'row'}, pill(`Лазер: ${laser.title || laser.name}`, 'ok'), link('/experiments', 'Все лазеры')) : null,
      h('input', {type: 'search', value: query, placeholder: 'Поиск по названию, лазеру, титану', 'aria-label': 'Поиск эксперимента',
        onChange: (ev) => { sessionStorage.setItem('experiment-search', ev.target.value); reload(); }}),
      h('select', {'aria-label': 'Состояние эксперимента', onChange: (ev) => { sessionStorage.setItem('experiment-status', ev.target.value); reload(); }},
        [['all', 'Все'], ['needs_review', 'Нужна проверка'], ['plate_ready', 'Ждут фото'], ['accepted', 'Приняты']].map(([v, l]) => h('option', {value: v, selected: v === wantedStatus}, l))),
      Tasks.select(wantedTask, {empty: 'Все задачи', aria: 'Задача гравировки',
        onChange: (value) => { sessionStorage.setItem('experiment-task', value); reload(); }}));

    const insightCards = [...latest.values()].sort((a, b) =>
      ['line', 'text', 'color', 'image'].indexOf(a.purpose) - ['line', 'text', 'color', 'image'].indexOf(b.purpose)).map((finding) =>
      h('article', {class: 'dashboard-insight'},
        h('div', {class: 'dashboard-item-top'}, h('strong', {}, PURPOSE[finding.purpose] || finding.purpose),
          pill(finding.status === 'candidate' ? 'Кандидат' : 'Нужен тест', finding.status === 'candidate' ? 'ok' : 'warn')),
        h('p', {class: 'dashboard-insight-preview', title: finding.summary}, finding.summary),
        h('details', {class: 'dashboard-details'}, h('summary', {}, 'Полный вывод и следующий шаг'),
          h('p', {}, finding.summary), h('p', {}, finding.next_test),
          settingSummary(finding.parameters || finding.evidence?.parameters)
            ? h('p', {}, 'Измеренный режим: ' + settingSummary(finding.parameters || finding.evidence?.parameters)) : null,
          link(`/analysis/${finding.pair_id}`, `Измерения · проверка №${finding.pair_id}`))));
    const devicePicker = devices.length > 1 ? h('select', {class: 'dashboard-device', 'aria-label': 'Лазер для выводов',
      onChange: (event) => { sessionStorage.setItem('experiment-dashboard-device', event.target.value); reload(); }},
      devices.map((device) => h('option', {value: device.id, selected: device.id === selectedDevice.id}, device.name))) : null;
    const goalPicker = h('select', {'aria-label': 'Цель исследования', onChange: (event) => {
      sessionStorage.setItem('experiment-dashboard-goal', event.target.value); reload();
    }}, goals.map((goal) => h('option', {value: goal.id, selected: goal.id === selectedGoal.id}, goal.name)));
    const materialPicker = h('select', {'aria-label': 'Материал и заготовка', onChange: (event) => {
      sessionStorage.setItem('experiment-dashboard-material', event.target.value); reload();
    }}, materials.map((material) => h('option', {value: material.id, selected: material.id === selectedMaterial?.id},
      [material.name, material.grade, material.batch].filter(Boolean).join(' · '))));
    // 200 нс предлагается, только если лазер даёт эту ступень; иначе длительность импульса выбирает оператор (DEC-043)
    const askPulse = guide?.plate && guide.plate.settings?.pulse_width == null;
    const pulseChoice = askPulse ? h('select', {'aria-label': 'Длительность импульса'}, h('option', {value: ''}, 'выберите'),
      (selectedDevice?.passport?.pulse_steps || []).map((s) => h('option', {value: s.pulse_width_ns}, `${s.pulse_width_ns} нс`))) : null;
    const nextPlate = guide?.plate ? btn('Создать следующий тест', async (ev) => {
      const self = ev.currentTarget;
      if (askPulse && pulseChoice.value === '') return App.fail(new Error('Выберите длительность импульса из ступеней лазера'));
      self.disabled = true; self.textContent = 'Создаём плату…';
      try {
        const made = await App.post('/application-guide/next-plate', {
          device_id: selectedDevice.id, material_id: selectedMaterial.id, goal: selectedGoal.id, pulse_width: askPulse ? +pulseChoice.value : null});
        toast(`Создана плата ${made.name}`, 'ok'); App.go('/experiment/plan-' + made.plan_id);
      } catch (error) { self.disabled = false; self.textContent = 'Создать следующий тест'; App.fail(error); }
    }, 'primary') : null;
    const taskPanel = h('section', {class: 'card dashboard-task'},
      h('div', {class: 'dashboard-task-head'}, h('div', {}, h('h3', {}, 'Рабочая задача'),
        h('p', {class: 'muted small'}, 'Один материал и одна цель: тест → RAW-фото → вывод → следующий тест.')),
      guide?.finding ? pill(guide.finding.status === 'candidate' ? 'Кандидат' : 'Нужна проверка',
        guide.finding.status === 'candidate' ? 'ok' : 'warn') : pill('Нет готового режима', 'warn')),
      h('div', {class: 'dashboard-task-selectors'},
        field('Что хотим сделать', goalPicker),
        field('На каком материале', materialPicker),
        devices.length > 1 ? field('Каким лазером', devicePicker) : h('div', {class: 'dashboard-task-fixed'},
          h('small', {}, 'Лазер и линза'), h('strong', {}, [selectedDevice?.name, selectedDevice?.lens?.name].filter(Boolean).join(' · ')))),
      h('div', {class: 'dashboard-task-result'},
        h('div', {}, h('strong', {}, selectedGoal?.objective || 'Выберите цель и материал'),
          h('p', {}, guide?.message || 'Добавьте конкретную заготовку, чтобы получить следующий тест.'),
          guide?.finding ? h('p', {class: 'muted small'}, `Последний вывод: ${guide.finding.summary}`) : null,
          // REQ-020: на чём основан вывод — наблюдения, сколько гравировок и фото, чего не хватает в контексте
          guide?.support ? h('p', {class: 'muted small'}, `Задача: ${Tasks.name(guide.task.kind)} · основание — проверка №${guide.support.pair_id}`,
            guide.support.observation_ids.length ? `, наблюдения №${guide.support.observation_ids.join(', №')}` : '',
            ` · гравировок: ${guide.support.engravings}, фото: ${guide.support.photographs} · повторяемость не оценена`,
            ...(guide.support.missing_context.length ? [' · не хватает: ', ...Tasks.missing(guide.support.missing_context)] : [])) : null,
          settingSummary(guide?.finding?.parameters || guide?.finding?.evidence?.parameters)
            ? h('p', {class: 'muted small'}, 'Параметры наблюдения: ' + settingSummary(guide.finding.parameters || guide.finding.evidence.parameters)) : null),
        h('div', {class: 'dashboard-task-next'}, h('small', {}, 'Следующий шаг'),
          h('p', {}, guide?.next_step || 'Создайте материал и первую плату.'),
          pulseChoice ? field('Длительность импульса (у этого лазера нет ступени 200 нс)', pulseChoice) : null, nextPlate,
          guide?.pending_plan_id ? link('/plans/' + guide.pending_plan_id, 'Открыть созданную плату') : null)),
      guide?.plate ? h('p', {class: 'dashboard-task-foot'},
        `Плата: ${PLATE_TYPE[guide.plate.test_type] || guide.plate.test_type} · чистка перед тестом · исходная проверка ${guide.plate.source_pair_id ? '№' + guide.plate.source_pair_id : 'ещё не создана'}`) : null);
    return h('div', {class: 'experiment-dashboard'}, hero,
      taskPanel,
      h('div', {class: 'dashboard-columns exp-columns'},
        h('section', {class: 'card dashboard-panel'},
          h('div', {class: 'dashboard-panel-head'}, h('h3', {}, 'Эксперименты'), pill(laser ? `${shown.length} из ${experiments.length}` : experiments.length),
            pill(`${experiments.filter((e) => e.needs_review).length} к проверке`, experiments.some((e) => e.needs_review) ? 'warn' : '')),
          filters,
          ExperimentCards.list(shown, experiments.length ? 'Ничего не найдено: измените поиск, состояние или лазер.' : 'Экспериментов пока нет. Создайте плату или добавьте работу и фото.')),
        panel('Выводы для материала', latest.size, insightCards,
          'Принятый тест возможностей добавит сюда выводы по линиям, тексту, цвету и изображению.',
          link(`/devices/${selectedDevice.id}`, selectedDevice.name))));
  }});
})();
