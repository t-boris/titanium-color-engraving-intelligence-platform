/* Контекст новой работы (ux-work-creation-p0, REQ-001): лазер, линза, заготовка титана и источник измерений, с которых начинается новая
   работа и новый тест. Это последний явный выбор мастерской (GET /creation/context): он виден при создании, переходит с экрана на экран и
   меняется только явным шагом «Изменить», который до подтверждения говорит, что станет недоступно (POST /creation/context/impact).
   Контекст — только начало: у созданной работы свои лазер, линза, титан и источник, записанные в ней, и общий выбор их не меняет;
   открытая работа показывает свои (WorkContext.own). Текст — русский; сервер присылает коды и числа. */
'use strict';
const WorkContext = (() => {
  const {h, fill, btn, get, put, post, modal} = App;

  // что считает сервер для каждого результата (creation_context.RESULTS)
  const COUNTED = {photo: 'измеренных шкал серого (фотогравировка)', colour: 'измеренных цветов заливки (цветные области)',
    silhouette: 'проверенных рецептов заливки (силуэт)', lines: 'проверенных рецептов линий (линии)'};
  const WARNING = {
    none_left: (w) => `${COUNTED[w.result][0].toUpperCase()}${COUNTED[w.result].slice(1)}: было ${w.now}, у выбранной установки нет ни одной.`,
    fewer: (w) => `${COUNTED[w.result][0].toUpperCase()}${COUNTED[w.result].slice(1)}: было ${w.now}, станет ${w.after}.`,
    lens_unknown: () => 'Линза неизвестна: знания разных линз не смешиваются, измерения других линз сюда не попадут.',
    lens_not_installed: () => 'Эта линза сейчас не стоит на выбранном лазере.',
    titanium_differs: () => 'Другая марка титана: рецепты и цвета, измеренные на прежней, к этой не относятся.',
    source_unavailable: (w) => `Выбранный источник сейчас не подходит: ${I18N.tr(w.detail)}`,
    source_dropped: () => 'Цвета и шкалы будут браться из измерений этой мастерской, а не из выпуска лаборатории.',
  };
  const warningText = (w) => (WARNING[w.code] ? WARNING[w.code](w) : w.code);

  const stockName = (m) => (m ? [m.name, m.grade, m.batch && `партия ${m.batch}`].filter(Boolean).join(' · ') : 'не выбран');
  const laserName = (d) => (d ? d.title || d.name : 'не выбран');
  const lensName = (lens, basis) => (lens ? App.lensLabel(lens) + (basis === 'installed' ? ' (установлена на лазере)' : '') : 'неизвестна');
  const sourceName = (s) => (s ? s.label || 'выпуск подключённой лаборатории' : 'измерения этой мастерской');

  /** Строка из названия и значения: «Лазер: JPT». Список определений, чтобы чтец экрана называл значение вместе с названием. */
  const row = (name, value) => [h('dt', {}, name), h('dd', {}, value)];

  /** Контекст в виде списка «Лазер · Линза · Титан · Измерения». */
  function summary(context) {
    return h('dl', {class: 'work-context-list'}, row('Лазер', laserName(context.device)), row('Линза', lensName(context.lens, context.lens_basis)),
      row('Титан', stockName(context.material)), row('Измерения', sourceName(context.source)));
  }

  /** Контекст, потерявший запись (лазер, линза, заготовка или установка съёмки удалены): что именно и чем заменено. */
  function staleNote(context) {
    const names = {device: 'лазер', lens: 'линза', material: 'заготовка титана', capture_setup: 'установка съёмки'};
    const lost = (context.stale || []).map((k) => names[k]).filter(Boolean);
    return lost.length ? h('p', {class: 'alert warn small', role: 'status'}, `Прежний выбор больше не найден (${lost.join(', ')}); взят тот, что есть сейчас.`) : null;
  }

  /** Окно явного изменения контекста: выбор лазера, линзы, титана и источника, и под ним — что изменение сделает с тем, что можно начать.
      Пока человек не нажал «Применить», ничего не сохранено; предупреждения видны до подтверждения и не запрещают его. ``done(context)``
      получает контекст, как его сохранил сервер. ``source: false`` — форма сама выбирает источник измерений (старые формы создания): окно его не
      показывает и не меняет, а предупреждения считает при нынешнем источнике. */
  async function change(context, done, {source: withSource = true} = {}) {
    const [devices, lenses] = await Promise.all([get('/devices'), get('/lenses')]);
    const pick = App.laserLensPicker({devices, lenses}, {device: context.device_id, lens: context.lens_id == null ? 'unknown' : context.lens_id,
      defaultLens: 'installed', onChange: () => ask()});
    // one concrete record, chosen by a search among the records used last and not from a list of all (ux-growing-collections-p0, REQ-001); with no
    // shared choice yet it starts with the record used last
    const stock = MaterialPicker.create({value: context.material_id, initial: 'recent', name: 'Титан', onChange: () => ask()});
    const source = withSource ? LabSource.picker('vector', {onChange: () => ask()}) : null;
    const impact = h('div', {class: 'stack', role: 'status', 'aria-live': 'polite'});
    let asked = 0;
    const wanted = () => ({device_id: pick.deviceId(), lens_id: pick.lensId(), material_id: stock.value === '' ? null : +stock.value, source: sourceValue()});
    const sourceValue = () => {
      if (!withSource) return context.source || null;
      const value = source.value();
      if (!value) return null;
      const option = [...source.select.options].find((o) => o.value === source.select.value);
      return {...value, label: option ? option.textContent : null};
    };
    async function ask() {
      const mine = ++asked;
      const body = wanted();
      let report;
      try { report = await post('/creation/context/impact', body); }
      catch (e) { if (mine === asked) fill(impact, h('p', {class: 'alert bad', role: 'alert'}, e.message)); return; }
      if (mine !== asked) return;                                         // another choice was made meanwhile: that answer is for the choice before it
      fill(impact, !report.changed ? h('p', {class: 'muted small'}, 'Выбор не отличается от нынешнего.')
        : report.warnings.length ? [h('p', {class: 'small'}, h('strong', {}, 'Что изменится для новых работ и тестов')),
          h('ul', {class: 'small'}, report.warnings.map((w) => h('li', {class: 'alert warn'}, warningText(w)))),
          h('p', {class: 'muted small'}, 'Предупреждения не запрещают изменение. Созданные работы остаются с теми настройками, с которыми они сделаны.')]
          : h('p', {class: 'small'}, 'Для этого выбора есть всё, что было у прежнего. Созданные работы не меняются.'));
    }
    const dialog = modal('Контекст новой работы', h('div', {class: 'stack'},
      h('p', {class: 'small muted'}, 'С этого выбора начинаются новые работы и тесты. Работа, которая уже создана, хранит свой выбор и от этого не меняется.'),
      h('div', {class: 'grid g2'}, App.field('Лазер', pick.laser), App.field('Линза', pick.lens, 'знания разных лазеров и линз не смешиваются'),
        App.field('Титан', stock), withSource ? source.el : null), impact), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Применить', cls: 'primary', run: async (m) => {
        const saved = await put('/creation/context', wanted());
        m.close();
        if (done) done(saved);
      }}]);
    if (withSource) source.loaded.then(() => { selectSource(source, context.source); return ask(); }); else ask();
    return dialog;
  }

  /** В списке источников выбрать тот, что в контексте (список приходит позже окна): совпадение — по тем же идентификаторам выпуска. */
  function selectSource(picker, wanted) {
    if (!wanted) return;
    const key = (v) => (v ? JSON.stringify([v.release_id, v.laser, v.lens ?? null, v.material ?? null]) : null);
    for (let i = 1; i < picker.select.options.length; i++) {
      picker.select.value = String(i);
      if (key(picker.value()) === key(wanted)) return;
    }
    picker.select.value = '';
  }

  /** Полоса контекста над формой создания: что выбрано сейчас и кнопка «Изменить». ``onChange(context)`` вызывается после подтверждённой смены.
      ``update(context)`` перерисовывает полосу, ``context()`` — выбор, как он сейчас. */
  function strip(initial, {onChange = null, heading = 'Начинается с', source = true} = {}) {
    let current = initial, changeButton = null, opening = false;
    const body = h('div', {class: 'stack'});
    const el = h('section', {class: 'card work-context', 'aria-label': 'Контекст новой работы'}, body);
    const focus = () => { if (changeButton && changeButton.focus) changeButton.focus(); };
    const open = () => {
      if (opening) return;                                 // the button stays enabled and focused (the dialog gives the focus back to it): a second click is ignored
      opening = true;
      change(current, (saved) => { current = saved; draw(); if (onChange) onChange(saved); focus(); }, {source}).catch(App.fail).finally(() => { opening = false; });
    };
    const draw = () => {
      changeButton = btn('Изменить…', open, 'btn-small');
      fill(body, h('div', {class: 'row'}, h('strong', {}, heading), h('span', {class: 'spacer'}), changeButton), summary(current), staleNote(current),
        h('p', {class: 'small muted'}, 'Общий выбор: новая работа и новый тест начинаются с него. Созданная работа хранит свой и им не меняется.'));
    };
    draw();
    return {el, focus, context: () => current, update: (context) => { current = context; draw(); }};
  }

  /** Контекст открытой работы: её собственный, записанный в ней (лазер, линза, титан, источник). Только чтение: общий выбор его не меняет. */
  function own({device, lens, material, source, heading = 'Параметры этой работы'}) {
    return h('section', {class: 'work-context work-context-own', 'aria-label': heading},
      h('div', {class: 'row'}, h('strong', {}, heading)),
      summary({device, lens, lens_basis: null, material, source: source && source.kind === 'release' ? {label: `${source.lab_name}, ${LabSource.releaseName(source)}`} : null}),
      h('p', {class: 'small muted'}, 'Записано в работе. Общий выбор для новых работ её не меняет.'));
  }

  return {summary, strip, change, own, warningText, selectSource, COUNTED, stockName, laserName, lensName, sourceName};
})();
