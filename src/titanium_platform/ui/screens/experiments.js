/* Эксперименты одним списком: каждый открывается целиком (плата, фото с наложением, результат); рядом выводы для материала (REQ-028).
   Один экран без прокрутки страницы (REQ-044, DEC-080): слева список с фильтрами (прокручивается только он), справа рабочая задача
   и под ней выводы для материала. Боковое меню остаётся. */
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
  const panel = (title, count, items, empty, action) => h('section', {class: 'os-col ex-find'},
    h('div', {class: 'os-col-head'}, h('h3', {}, title), pill(count), h('span', {class: 'spacer'}), action),
    h('div', {class: 'os-scroll'}, items.length ? h('div', {class: 'ex-insights'}, ...items) : h('p', {class: 'muted small'}, empty)));
  const action = (route, label, primary) => h('a', {class: 'btn btn-small' + (primary ? ' primary' : ''), href: '#' + route}, label);

  App.register({id: 'experiments', async render(ctx) {
    const [experiments, devices] = await Promise.all([get('/experiments'), get('/devices')]);
    const rememberedDevice = Number(sessionStorage.getItem('experiment-dashboard-device'));
    const selectedDevice = devices.find((device) => device.id === rememberedDevice) || devices[0];
    const reload = () => App.render({preserveScroll: true});
    const hero = h('div', {class: 'os-head ex-head'},
      h('div', {class: 'ex-title'}, h('h2', {}, 'Эксперименты'), h('p', {class: 'sub'}, 'Каждый эксперимент открывается целиком: плата, фото с наложением, результат')),
      h('span', {class: 'spacer'}),
      h('div', {class: 'ex-actions'},
        action('/research', 'AI-исследователь'),
        action('/colors', 'Карта цветов'),
        btn('Создать плату', () => PlateDialog.open(devices, null, reload), 'primary btn-small', !devices.length),
        action('/ingest', 'Добавить работу и фото')));
    if (!devices.length) return h('div', {class: 'os'}, hero,
      h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер и установите линзу'), link('/devices', 'Лазеры')));

    // ?device=<id>: the experiments of one laser, the list its page links to (no separate list there). The search, the state, the
    // engraving task (REQ-020), the order and the pages are the shared list's (ExperimentCards.list, DEC-090), the same as on the laser's page.
    const laser = devices.find((device) => String(device.id) === String(ctx.query.device)) || null;
    const shown = laser ? experiments.filter((e) => e.device_id === laser.id) : experiments;
    const scope = laser ? h('div', {class: 'ex-filters'},
      h('span', {class: 'row'}, pill(`Лазер: ${laser.title || laser.name}`, 'ok'), link('/experiments', 'Все лазеры'))) : null;

    const taskSlot = h('section', {class: 'os-col ex-task'});
    const findingsSlot = h('section', {class: 'os-col ex-find'});
    const photoSlot = h('section', {class: 'os-col ex-find'});
    const loading = (slot, title) => App.fill(slot, h('h3', {}, title), h('p', {role: 'status'}, 'Загрузка…'));
    const failed = (slot, title, error, retry) => App.fill(slot, h('h3', {}, title),
      h('p', {class: 'alert bad', role: 'alert'}, error.message), btn('Повторить', retry, 'btn-small'));
    const put = (slot, contents) => App.fill(slot, ...Array.from(contents.childNodes));
    loading(taskSlot, 'Рабочая задача'); loading(findingsSlot, 'Выводы для материала'); loading(photoSlot, 'Фотогравировка');
    let goals, selectedMaterial, selectedGoal, setup, findings = [], photoKinds = null;
    let findingsReady = false;
    function showFindings() {
      if (!findingsReady) return;
      const latest = new Map();
      for (const finding of findings.filter((f) => f.material_id === selectedMaterial?.id && f.lens_id === selectedDevice?.lens?.id))
        if (!latest.has(finding.purpose)) latest.set(finding.purpose, finding);
    // the image purpose of a capability plate cannot judge a picture; the photographed photo engravings of this titanium can
    const photoBest = (photoKinds?.kinds || []).filter((k) => k.best && k.best.score != null).sort((a, b) => b.best.score - a.best.score)[0];
    const insightCards = [...latest.values()].sort((a, b) =>
      ['line', 'text', 'color', 'image'].indexOf(a.purpose) - ['line', 'text', 'color', 'image'].indexOf(b.purpose)).map((finding) => {
      const photo = finding.purpose === 'image' && finding.status !== 'candidate' ? photoBest : null;
      const preview = photo ? `Фотогравировка измерена: лучше всего вышел вид «${PhotoModes.label(photo.kind)}» (оценка `
        + `${String(+photo.best.score.toFixed(2)).replace('.', ',')} по фото №${photo.best.source.pair_id}). Что делает каждая настройка и какую плату сделать дальше — в панели «Фотогравировка».`
        : finding.summary;
      return h('article', {class: 'dashboard-insight'},
        h('div', {class: 'dashboard-item-top'}, h('strong', {}, PURPOSE[finding.purpose] || finding.purpose),
          photo ? pill('Фото измерено', 'ok') : pill(finding.status === 'candidate' ? 'Кандидат' : 'Нужен тест', finding.status === 'candidate' ? 'ok' : 'warn')),
        h('p', {class: 'dashboard-insight-preview', title: preview}, preview),
        h('details', {class: 'dashboard-details'}, h('summary', {}, 'Полный вывод и следующий шаг'),
          h('p', {}, finding.summary), h('p', {}, finding.next_test),
          settingSummary(finding.parameters || finding.evidence?.parameters)
            ? h('p', {}, 'Измеренный режим: ' + settingSummary(finding.parameters || finding.evidence?.parameters)) : null,
          link(`/analysis/${finding.pair_id}`, `Измерения · проверка №${finding.pair_id}`)));
    });
      put(findingsSlot, panel('Выводы для материала', latest.size, insightCards,
        'Принятый тест возможностей добавит сюда выводы по линиям, тексту, цвету и изображению.', link(`/devices/${selectedDevice.id}`, selectedDevice.name)));
    }
    function showTask(guide) {
    const devicePicker = devices.length > 1 ? h('select', {class: 'dashboard-device', 'aria-label': 'Лазер для выводов',
      onChange: (event) => { sessionStorage.setItem('experiment-dashboard-device', event.target.value); reload(); }},
      devices.map((device) => h('option', {value: device.id, selected: device.id === selectedDevice.id}, device.name))) : null;
    const goalPicker = h('select', {'aria-label': 'Цель исследования', onChange: (event) => {
      sessionStorage.setItem('experiment-dashboard-goal', event.target.value); reload();
    }}, goals.map((goal) => h('option', {value: goal.id, selected: goal.id === selectedGoal.id}, goal.name)));
    const materialPicker = MaterialPicker.create({value: selectedMaterial ? selectedMaterial.id : undefined, name: 'Материал и заготовка', onChange: (record) => {
      if (!record) return;
      sessionStorage.setItem('experiment-dashboard-material', record.id); reload();
    }});
    // 200 нс предлагается, только если лазер даёт эту ступень; иначе длительность импульса выбирает оператор (DEC-043)
    const askPulse = guide?.plate && guide.plate.settings?.pulse_width == null;
    const plateForm = Forms.create();
    const pulseSelect = askPulse ? h('select', {}, h('option', {value: ''}, 'выберите'),
      (selectedDevice?.passport?.pulse_steps || []).map((s) => h('option', {value: s.pulse_width_ns}, `${s.pulse_width_ns} нс`))) : null;
    const pulseChoice = askPulse ? plateForm.add('pulse', 'Длительность импульса', pulseSelect, {required: true, help: 'у этого лазера нет ступени 200 нс',
      read: () => (pulseSelect.value === '' ? {ok: false, message: 'Выберите длительность импульса из ступеней лазера'} : {ok: true, value: +pulseSelect.value})}) : null;
    const nextPlate = guide?.plate ? btn('Создать следующий тест', async (ev) => {
      const self = ev.currentTarget;
      const v = plateForm.collect();
      if (!v) return;                                                  // the reason stands beside the box
      self.disabled = true; self.textContent = 'Создаём плату…';
      try {
        const made = await App.post('/application-guide/next-plate', {
          device_id: selectedDevice.id, material_id: selectedMaterial.id, goal: selectedGoal.id, pulse_width: askPulse ? v.pulse : null});
        toast(`Создана плата ${made.name}`, 'ok'); App.go('/experiment/plan-' + made.plan_id);
      } catch (error) { self.disabled = false; self.textContent = 'Создать следующий тест'; plateForm.fail(error); }
    }, 'primary') : null;
    // REQ-020: на чём основан вывод — наблюдения, сколько гравировок и фото, чего не хватает в контексте
    const manyObservations = Boolean(guide?.support) && guide.support.observation_ids.length > SourceRefs.SHORT;    // a count and a list, not a sentence (ux-growing-collections-p0)
    const evidence = [
      guide?.support ? h('p', {class: 'muted small'}, `Задача: ${Tasks.name(guide.task.kind)} · основание — проверка №${guide.support.pair_id}`,
        guide.support.observation_ids.length && !manyObservations ? `, наблюдения №${guide.support.observation_ids.join(', №')}` : '',
        ` · гравировок: ${guide.support.engravings}, фото: ${guide.support.photographs} · повторяемость не оценена`,
        ...(guide.support.missing_context.length ? [' · не хватает: ', ...Tasks.missing(guide.support.missing_context)] : [])) : null,
      manyObservations ? SourceRefs.observations(guide.support.observation_ids, {label: 'Наблюдения-основания'}) : null,
      settingSummary(guide?.finding?.parameters || guide?.finding?.evidence?.parameters)
        ? h('p', {class: 'muted small'}, 'Параметры наблюдения: ' + settingSummary(guide.finding.parameters || guide.finding.evidence.parameters)) : null].filter(Boolean);
    const taskNote = 'Один материал и одна цель: тест → RAW-фото → вывод → следующий тест.';
    const taskPanel = h('section', {class: 'os-col ex-task'},
      h('div', {class: 'os-col-head'}, h('h3', {title: taskNote}, 'Рабочая задача'), h('span', {class: 'muted small ex-note', title: taskNote}, taskNote), h('span', {class: 'spacer'}),
      guide?.finding ? pill(guide.finding.status === 'candidate' ? 'Кандидат' : 'Нужна проверка',
        guide.finding.status === 'candidate' ? 'ok' : 'warn') : pill('Нет готового режима', 'warn')),
      h('div', {class: 'os-scroll ex-task-body'},
      h('div', {class: 'dashboard-task-selectors'},
        field('Что хотим сделать', goalPicker),
        field('На каком материале', materialPicker),
        devices.length > 1 ? field('Каким лазером', devicePicker) : h('div', {class: 'dashboard-task-fixed'},
          h('small', {}, 'Лазер и линза'), h('strong', {}, [selectedDevice?.name, selectedDevice?.lens?.name].filter(Boolean).join(' · ')))),
      h('div', {class: 'dashboard-task-result'},
        h('div', {}, h('strong', {}, selectedGoal?.objective || 'Выберите цель и материал'),
          h('p', {}, guide?.message || 'Добавьте конкретную заготовку, чтобы получить следующий тест.'),
          guide?.finding ? h('p', {class: 'muted small ex-last'}, `Последний вывод: ${guide.finding.summary}`) : null,
          evidence.length ? h('details', {class: 'dashboard-details ex-evidence'}, h('summary', {}, 'Основание вывода и параметры'), ...evidence) : null),
        h('div', {class: 'dashboard-task-next'}, h('small', {}, 'Следующий шаг'),
          h('p', {}, guide?.next_step || 'Создайте материал и первую плату.'),
          pulseChoice, nextPlate, guide?.plate ? plateForm.error : null,
          guide?.pending_plan_id ? link('/plans/' + guide.pending_plan_id, 'Открыть созданную плату') : null)),
      guide?.plate ? h('p', {class: 'dashboard-task-foot'},
        `Плата: ${PLATE_TYPE[guide.plate.test_type] || guide.plate.test_type} · чистка перед тестом · исходная проверка ${guide.plate.source_pair_id ? '№' + guide.plate.source_pair_id : 'ещё не создана'}`) : null));
      put(taskSlot, taskPanel);
    }
    async function loadFindings() {
      loading(findingsSlot, 'Выводы для материала');
      try { findings = await get(`/devices/${selectedDevice.id}/findings`); findingsReady = true; showFindings(); }
      catch (e) { failed(findingsSlot, 'Выводы для материала', e, loadFindings); }
    }
    async function loadPhoto() {
      if (!setup) { photoSlot.hidden = true; return; }
      photoSlot.hidden = false; loading(photoSlot, 'Фотогравировка');
      try {
        photoKinds = await get(`/photo-knowledge?device_id=${setup.device_id}${setup.lens_id == null ? '' : `&lens_id=${setup.lens_id}`}&material_id=${setup.material_id}`);
        put(photoSlot, panel('Фотогравировка: что предлагает лаборатория', photoKinds.kinds.filter((k) => k.proposal).length,
          PhotoQuality.kindCards(photoKinds, setup), 'Видов фотогравировки нет.'));
        // Do not replace a finding while someone is reading or operating its disclosure.
        if (!findingsSlot.contains(document.activeElement) && !Array.from(findingsSlot.querySelectorAll('details')).some((d) => d.open)) showFindings();
      } catch (e) { failed(photoSlot, 'Фотогравировка', e, loadPhoto); }
    }
    async function loadGuide() {
      if (!selectedMaterial || !selectedGoal) { showTask(null); return; }
      loading(taskSlot, 'Рабочая задача');
      try { showTask(await get(`/application-guide?device_id=${selectedDevice.id}&material_id=${selectedMaterial.id}&goal=${selectedGoal.id}`)); }
      catch (e) { failed(taskSlot, 'Рабочая задача', e, loadGuide); }
    }
    async function loadGoals() {
      loading(taskSlot, 'Рабочая задача');
      try {
        goals = await get('/application-goals');
        selectedGoal = goals.find((goal) => goal.id === sessionStorage.getItem('experiment-dashboard-goal')) || goals[0];
        loadGuide();
      } catch (e) { failed(taskSlot, 'Рабочая задача', e, loadGoals); }
    }
    async function loadContext() {
      loading(taskSlot, 'Рабочая задача'); loading(findingsSlot, 'Выводы для материала'); loading(photoSlot, 'Фотогравировка');
      try {
        const rememberedMaterial = Number(sessionStorage.getItem('experiment-dashboard-material'));
        selectedMaterial = (rememberedMaterial ? await MaterialPicker.one(rememberedMaterial).catch(() => null) : null) || await MaterialPicker.lastUsed();
        setup = selectedMaterial ? {device_id: selectedDevice.id, lens_id: selectedDevice.lens?.id ?? null, material_id: selectedMaterial.id} : null;
        loadFindings(); loadPhoto(); loadGoals();
      } catch (e) {
        failed(taskSlot, 'Рабочая задача', e, loadContext);
        App.fill(findingsSlot, h('p', {class: 'small'}, 'Нужны данные материала.'));
        photoSlot.hidden = true;
      }
    }
    loadContext();
    return h('div', {class: 'os ex'}, hero,
      h('div', {class: 'os-body ex-body'},
        h('section', {class: 'os-col ex-list'},
          h('div', {class: 'os-col-head'}, h('h3', {}, 'Эксперименты'), pill(laser ? `${shown.length} из ${experiments.length}` : experiments.length),
            pill(`${experiments.filter((e) => e.needs_review).length} к проверке`, experiments.some((e) => e.needs_review) ? 'warn' : '')),
          scope,
          h('div', {class: 'os-scroll'}, ExperimentCards.list(shown, {id: 'experiments', noResults: 'Ничего не найдено: измените поиск, состояние или лазер.',
            empty: experiments.length ? 'Ничего не найдено: измените поиск, состояние или лазер.' : 'Экспериментов пока нет. Создайте плату или добавьте работу и фото.'}))),
        h('div', {class: 'ex-right'}, taskSlot, findingsSlot, photoSlot)));
  }});
})();
