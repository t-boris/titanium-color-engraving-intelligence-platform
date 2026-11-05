/* Векторная работа (REQ-021, REQ-042, DEC-065, DEC-073): изображение → редактируемые контуры → обычный файл LightBurn, одна
   связанная запись. Фотография («Фото: цветные области») идёт двумя разделами: цвета и разбиение (vector-colours.js со
   своим блоком vector-split.js) и файл LightBurn с оценкой времени всей работы. Заливка, текст и линии обводятся как раньше: каждая
   группа настроек получает валидированный или производственный рецепт этого лазера, линзы и титана, режим LightBurn
   которого подходит задаче её областей; рецепт никогда не придумывается. Область без достаточных данных заштрихована на
   предпросмотре; пока такие области есть, экспорт недоступен. Файлы скачиваются через fetch: ошибка показывается на экране
   по-русски, на адрес API экран никогда не переходит. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, post, put, form, toast, fail, go, modal, table, num, labText, swatch, facts} = App;
  const STRATEGIES = [['photo', 'Фото: цветные области'], ['fill', 'Заливка силуэта'], ['text', 'Текст'], ['line', 'Линии (центральные)']];
  const STRATEGY_NAME = {...Object.fromEntries(STRATEGIES), color: 'Цветные области (обводка)'};
  const DETAIL = [['coarse', 'Крупно'], ['medium', 'Средне'], ['fine', 'Детально']];
  const TASKS = [['color', 'Цвет'], ['fill', 'Заливка'], ['text', 'Текст'], ['line', 'Линия'], ['tonal', 'Тон']];
  const STATUS = {matched: ['Есть рецепт', 'ok'], chosen: ['Рецепт выбран вручную', 'ok'], weak: ['Мало данных', 'bad'], excluded: ['Без рецепта: исключена', '']};
  const WEAK_FIRST = {weak: 0, excluded: 1, chosen: 2, matched: 3};             // «Сначала без данных»: what still keeps the file from export first
  const MODE = {Scan: 'заливка (Fill)', Cut: 'линия (Line)', OffsetFill: 'заливка по контуру (Offset Fill)', 'Offset Fill': 'заливка по контуру (Offset Fill)'};
  const OPS = {trace: 'обводка изображения', set_task: 'задача области', set_layer: 'группа настроек области', delete: 'удаление области',
    merge: 'объединение областей', set_tolerance: 'точность контура', revert: 'возврат к версии', set_settings: 'настройки группы',
    exclude: 'исключение области', include: 'возврат исключённой области', set_threshold: 'порог ΔE', allow_questioned: 'параметры под вопросом',
    to_designer: 'цвет передан планировщику', copy: 'копия другой работы'};
  const DOCUMENT_OPS = ['trace', 'set_task', 'set_layer', 'delete', 'merge', 'set_tolerance', 'revert'];
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 1)} кГц · ${num(p.speed, 0)} мм/с · Q-Pulse ${num(p.pulse_width, 0)} нс`
    + (p.line_interval == null ? '' : ` · шаг ${num(p.line_interval, 3)} мм`) + ` · ${p.passes ?? 1} проход(а)`;
  const stability = (s) => (s.assessed ? 'дисперсия ' + num(s.variance) : 'стабильность не оценена');
  const material = (m) => [m.name, m.grade, m.batch && `партия ${m.batch}`].filter(Boolean).join(' · ');
  const svgSrc = (svg) => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);

  function startForm(lists, ctx) {
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens, onChange: () => { loadPalette(); loadRules(); }});
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    // the titanium is one concrete record chosen by a search among the records used last, never from a list of all (ux-growing-collections-p0, REQ-001);
    // it starts with the workshop's last choice (ux-work-creation-p0) and else with the record used last
    const stock = MaterialPicker.create({value: ctx.start && ctx.start.material != null ? ctx.start.material : undefined, initial: 'recent', name: 'Титан',
      onChange: () => loadPalette()});
    // feature electron, REQ-085: a photograph work may take its colours from a connected laboratory release instead of the own measurements;
    // the own measurements are the default, a laboratory is never chosen for the operator
    const source = LabSource.picker('vector', {onChange: () => loadPalette()});
    const img = h('input', {type: 'file', accept: 'image/*'});
    const name = h('input', {placeholder: 'Название работы'}), width = Forms.numberInput(Q.workWidth, {value: 60});
    const strategy = h('select', {}, STRATEGIES.map(([id, label]) => h('option', {value: id}, label)));
    const colours = Forms.numberInput(Q.photoColours, {value: 12});
    const detail = h('select', {}, DETAIL.map(([v, l]) => h('option', {value: v, selected: v === 'medium'}, l)));
    const algorithm = VectorSplit.picker('slic');
    algorithm.hint.setAttribute('style', 'grid-column:1 / -1');
    const faces = h('input', {type: 'checkbox', checked: true});
    const maxTime = Forms.numberInput(Q.maxTime, {placeholder: 'без предела'});
    const asShot = h('input', {type: 'checkbox'});
    const thr = Forms.numberInput(Q.deltaE, {placeholder: 'из правил'});
    // the delta E tolerance is never invented (conversion._threshold): the form shows at once whether the rules of the laser and lens hold one,
    // and a tolerance typed while they hold none is saved to them, once («Запомнить», on by default)
    const thrHint = h('span', {class: 'small muted'});
    const remember = h('input', {type: 'checkbox', checked: true});
    const rememberRow = h('label', {class: 'row small', hidden: true}, remember, h('span', {}, 'Запомнить для этого лазера с линзой'));
    let savedTolerance;                                   // in the rules: a number, null when none is saved, undefined while not known
    const grey = Forms.numberInput(Q.greyThreshold, {placeholder: 'авто (Оцу)'});
    const tolerance = Forms.numberInput(Q.vectorTolerance, {value: 0.08});
    const markers = h('input', {type: 'checkbox'}), clean = h('input', {type: 'checkbox', checked: true});
    // REQ-020: главная задача работы следует из стратегии, пока оператор не выбрал другую; у каждой области — своя задача
    const STRATEGY_TASK = {photo: 'color_image', fill: 'fill', text: 'text', line: 'line'};
    const task = Tasks.chooser(STRATEGY_TASK[strategy.value], {hint: 'главная задача работы; задачу каждой области можно изменить после обводки'});
    const info = h('div', {});
    // the fields of the form: each says what it is, whether it is required, its unit and its permitted values (from the server's own rules), and a wrong one
    // says why beside itself; the form keeps everything typed (ux-save-feedback-p0, REQ-003)
    const phoPhoto = () => strategy.value === 'photo';
    // a field of the group that is not shown (the photograph's or the tracing's) is not read: it cannot be wrong where it cannot be seen
    const onlyPhoto = (read) => () => (phoPhoto() ? read() : {ok: true, value: null});
    const onlyTrace = (read) => () => (phoPhoto() ? {ok: true, value: null} : read());
    const laserField = f.add('laser', 'Лазер', pick.laser, {required: true,
      read: () => (pick.deviceId() ? {ok: true, value: pick.deviceId()} : {ok: false, message: 'Выберите лазер'})});
    const lensField = f.add('lens', 'Линза', pick.lens, {help: 'цвета и рецепты — измерения этого лазера с этой линзой', read: () => ({ok: true, value: pick.lensValue()})});
    const imageField = f.add('image', 'Изображение', App.filePick(img, 'Выбрать изображение'), {required: true,
      read: () => (img.files[0] ? {ok: true, value: img.files[0]} : {ok: false, message: 'Добавьте изображение для векторной работы'})});
    const nameField = f.add('name', 'Название работы', name, {required: true});               // conversion: «give the plan a name»
    const widthField = f.add('width', 'Ширина работы', width, {quantity: 'workWidth', required: true});
    const strategyField = f.add('strategy', 'Стратегия', strategy, {required: true, help: 'фото — цветные области по картинке; заливка, текст и линии — по тёмному силуэту'});
    const stockHint = h('span', {class: 'small muted'});      // «Фото» takes every plate of this grade (palette.vector_palette), the others this plate only
    const stockField = f.add('material', 'Титан', stock, {required: true, help: stockHint,
      read: () => (stock.value ? {ok: true, value: stock.value} : {ok: false, message: 'Выберите титан'})});
    // the tolerance is required only while the rules of the laser and lens hold none (conversion._threshold)
    const thrField = f.add('threshold', 'Допуск ΔE', thr, {quantity: 'deltaE', help: thrHint,
      read: () => (thr.value === '' ? (savedTolerance === null ? {ok: false, message: 'Задайте допуск ΔE: для этого лазера с линзой он не сохранён'} : {ok: true, value: null})
        : Forms.readNumber(thr, Q.deltaE, {}))});
    const tolLabelText = () => (phoPhoto() ? 'Сглаживание границ' : 'Точность контура');
    const toleranceField = f.add('tolerance', tolLabelText(), tolerance, {quantity: 'vectorTolerance', required: true});
    const coloursField = f.add('colours', 'Число цветов', colours, {required: true, constraint: '', help: '2–29, с маркерами 2–28: чистка — первый слой',
      read: onlyPhoto(() => Forms.readNumber(colours, {...Q.photoColours, max: markers.checked ? 28 : 29}, {required: true}))});
    const detailField = f.add('detail', 'Детальность', detail, {required: true, help: 'крупно — спокойные большие области, детально — мелкие',
      read: onlyPhoto(() => ({ok: true, value: detail.value}))});
    const algorithmField = f.add('algorithm', 'Алгоритм разбиения', algorithm.select, {required: true, read: onlyPhoto(() => ({ok: true, value: algorithm.select.value}))});
    const maxTimeField = f.add('max_time', 'Наибольшее время гравировки', maxTime, {quantity: 'maxTime', help: 'пусто — без предела; медленные цвета автоматика не берёт',
      read: onlyPhoto(() => Forms.readNumber(maxTime, Q.maxTime, {}))});
    const greyField = f.add('grey', 'Порог серого', grey, {quantity: 'greyThreshold', help: 'пусто — автоматически', read: onlyTrace(() => Forms.readNumber(grey, Q.greyThreshold, {}))});
    // поля фотографии и поля обводки показываются по стратегии; чистка у фотографии всегда первая (DEC-073)
    const photoFields = h('div', {class: 'grid g2'}, algorithmField, coloursField,
      algorithm.hint, detailField,
      maxTimeField,
      h('label', {class: 'row'}, faces, h('span', {}, 'Искать лица: глаза и губы делятся подробнее')),
      h('label', {class: 'row'}, asShot, h('span', {}, 'Включить цвета без привязки (сняты без эталона и без чистого титана)')));
    const traceFields = h('div', {class: 'grid g2'}, greyField,
      h('label', {class: 'row'}, clean, h('span', {}, 'Чистка первым слоем (C00)')));
    const photo = phoPhoto;
    const switchFields = () => {
      photoFields.hidden = !photo(); traceFields.hidden = photo(); source.el.hidden = !photo();
      toleranceField.firstChild.textContent = tolLabelText();
      stockHint.textContent = photo() ? 'цвета — измерения титана этой марки с любой его пластины'
        : 'рецепты — только измеренные на этой заготовке';
      tolerance.value = photo() ? 0.08 : 0.05;
      colours.max = markers.checked ? '28' : '29';
      task.set(STRATEGY_TASK[strategy.value]);
      loadPalette();
    };
    strategy.addEventListener('change', switchFields);
    markers.addEventListener('change', () => { colours.max = markers.checked ? '28' : '29'; });

    async function loadPalette() {
      if (!stock.value) return fill(info);
      if (photo()) {
        const src = source.value(), asked = JSON.stringify(src);
        let p;
        try { p = src ? await post('/labs/palette', src) : await get(`/vector-palette?${pick.query()}&material_id=${stock.value}`); }
        catch (e) { return fill(info, h('p', {class: 'alert bad'}, e.message)); }
        if (asked !== JSON.stringify(source.value())) return;      // the source changed meanwhile
        const asShotCount = p.entries.filter((e) => e.basis === 'as-shot').length;
        const whose = src ? `лаборатории «${p.source.lab_name}» (${LabSource.releaseName(p.source)}; ${LabSource.setupName(p.source)})`
          : 'этого лазера, линзы и титана этой марки (с любой плиты)';
        return fill(info, p.entries.length
          ? h('p', {class: 'muted small'}, `Измеренных цветов заливки ${whose}: ${p.entries.length}`,
            asShotCount ? `, из них без привязки к эталону: ${asShotCount}` : '', '. Каждому цвету картинки достанется самый быстрый цвет в пределах допуска ΔE.',
            src && p.conditions && p.conditions.length ? ' ' + p.conditions.map((c) => I18N.tr(c)).join(' ') : '')
          : h('div', {class: 'alert warn'}, `У ${whose} нет измеренных цветов заливки: разбить можно, раскрасить будет нечем.`));
      }
      let palette;
      try { palette = await get(`/vector/palette?${pick.query()}&material_id=${stock.value}`); } catch (e) { return fill(info, h('p', {class: 'alert bad'}, e.message)); }
      const lines = palette.filter((e) => e.mode === 'Cut').length;
      fill(info, palette.length
        ? h('p', {class: 'muted small'}, `Рецептов этого лазера, линзы и титана: ${palette.length} (заливка — ${palette.length - lines}, линия — ${lines}). `,
          'Области, для которых рецепта нет, будут отмечены, и их можно передать планировщику экспериментов.')
        : h('div', {class: 'alert warn'}, 'Для этого лазера, линзы и титана нет валидированных или производственных рецептов: все области окажутся без данных. ',
          link(`/designer?${pick.route()}`, 'Планировщик экспериментов')));
    }
    async function loadRules() {
      const asked = pick.query();
      let rules = null;
      try { rules = await get('/rules?' + asked); } catch (_) { rules = null; }
      if (asked !== pick.query()) return;                // the laser or the lens changed meanwhile
      savedTolerance = rules ? rules.delta_tolerance : undefined;
      showTolerance();
    }
    function showTolerance() {
      const none = savedTolerance === null, de = savedTolerance == null ? '' : String(+(+savedTolerance).toFixed(2));   // 5, not 5.00
      thr.setAttribute('placeholder', savedTolerance != null ? `из правил: ${de}` : none ? 'задайте' : 'из правил');
      thr.setAttribute('aria-invalid', none && thr.value === '' ? 'true' : 'false');
      rememberRow.hidden = !none;
      fill(thrHint, savedTolerance != null
        ? `пусто — ΔE ${de} из правил этого лазера с линзой; число здесь — только для этой работы`
        : none ? 'Для этого лазера с линзой допуск не сохранён — задайте его. Внутри допуска берётся самый быстрый цвет; ΔE 1 едва заметно, '
          + '2–3 — мало, 5 — две гравировки одного рецепта ещё совпадают.'
          : 'пусто — допуск из правил этого лазера с линзой');
    }
    thr.addEventListener('input', showTolerance);

    const submit = btn('Создать работу', async (ev) => {
      const v = f.collect();
      if (!v) return;                                                // every wrong box says why beside itself; the dialog of the work keeps all that was typed
      if (!task.check()) return f.fail(new Error('Цели задачи заполнены неверно: исправьте отмеченные поля'));
      const fd = new FormData();
      fd.append('device_id', v.laser); fd.append('lens_id', v.lens); fd.append('material_id', v.material); fd.append('name', v.name);
      fd.append('width_mm', v.width); fd.append('strategy', v.strategy); fd.append('tolerance_mm', v.tolerance);
      fd.append('markers', markers.checked); fd.append('image', v.image);
      if (v.threshold != null) fd.append('threshold', v.threshold);
      task.append(fd);
      if (photo()) {
        fd.append('n_colors', v.colours); fd.append('algorithm', v.algorithm); fd.append('detail', v.detail); fd.append('faces', faces.checked); fd.append('include_as_shot', asShot.checked);
        if (v.max_time != null) fd.append('max_time', v.max_time);
        if (source.value()) fd.append('source', JSON.stringify(source.value()));
      } else {
        fd.append('clean', clean.checked);
        if (v.grey != null) fd.append('grey_threshold', v.grey);
      }
      const self = ev.currentTarget;
      const end = App.landing(self);
      self.disabled = true;
      if (v.threshold != null && savedTolerance === null && remember.checked) {
        try {
          await put('/rules', {device_id: pick.deviceId(), lens_id: pick.lensId(), delta_tolerance: v.threshold});
          savedTolerance = v.threshold;
          showTolerance();
        } catch (e) { self.disabled = false; return f.fail(e); }
      }
      try {
        const j = await form('/vector', fd);
        App.rememberContext({device: pick.deviceId(), lens: pick.lensId(), material: stock.value, source: photo() ? source.value() : undefined});
        if (end.stillHere()) toast('Векторная работа создана', 'ok');
        end.go('/vector?plan=' + j.id, {title: 'Векторная работа создана', message: `Работа «${v.name}» создана. Откройте её: проверьте области и выгрузите файл LightBurn.`, openLabel: 'Открыть работу', goOptions: {}});
      } catch (e) { f.fail(e); self.disabled = false; }
    }, 'primary');
    switchFields();
    loadRules();
    // ux-work-creation-p0, REQ-001: the shared choice is changed from here by the dialog of the creation screen (it shows what the change makes
    // unavailable before «Применить»); the source of measurements stays this form's own picker, so the dialog leaves it out
    const shared = ctx.start && ctx.start.context ? WorkContext.strip(ctx.start.context, {heading: 'Общий выбор мастерской', source: false, onChange: (c) => {
      pick.setDevice(c.device_id, c.lens_id == null ? 'unknown' : c.lens_id);
      if (c.material_id != null) stock.value = String(c.material_id);
      loadPalette(); loadRules();
    }}) : null;
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Новая векторная работа'), h('p', {class: 'sub'}, 'Фотография делится на цветные области и раскрашивается измеренными цветами титана; заливка, текст и линии обводятся по силуэту. Результат — обычный файл LightBurn.')), h('span', {class: 'spacer'}), h('a', {class: 'btn btn-small', href: '#/vector'}, '← Мои работы')),
      shared ? shared.el : null,
      h('div', {class: 'card stack'}, h('div', {class: 'grid g2'},
        laserField, lensField, stockField, source.el, imageField,
        nameField, widthField, strategyField,
        h('div', {class: 'f'}, thrField, rememberRow),
        toleranceField),
        photoFields, traceFields, task.el,
        h('label', {class: 'row'}, markers, h('span', {}, 'Регистрационные маркеры и идентификатор вне изображения')),
        info, f.error, submit));
  }

  function settingsDialog(j, group, run) {
    const byId = Object.fromEntries(j.palette.map((e) => [e.id, e]));
    let chosen = group.chosen ? group.knowledge_id : null;
    const option = (value, label, extra) => h('label', {class: 'row'}, h('input', {type: 'radio', name: 'settings', checked: chosen === value, onChange: () => { chosen = value; }}), label, extra);
    const rows = [option(null, 'Ближайший подходящий рецепт (автоматически)')].concat(group.candidates.map((c) => {
      const e = byId[c.knowledge_id];
      return option(e.id, h('span', {}, swatch(e.lab), `K${e.id} · ${MODE[e.mode] || e.mode || 'режим не записан'}`),
        h('span', {class: 'muted small'}, `${params(e.parameters)} · расстояние ${num(c.distance)} · ожидаемая ошибка ΔE ${num(e.expected_delta_e)} · уверенность ${num(e.confidence)}`));
    }));
    modal(`Настройки группы «${group.key}»`, h('div', {class: 'stack'},
      h('p', {}, 'Только валидированные и производственные рецепты этого лазера, линзы и титана, режим LightBurn которых подходит задаче группы.'),
      group.candidates.length ? rows : h('p', {class: 'alert warn'}, 'Подходящих рецептов нет: области группы останутся без данных.')), [
      {label: 'Отмена', run: (x) => x.close()},
      {label: 'Применить', cls: 'primary', run: async (x) => { x.close(); await run({op: 'set_settings', group: group.key, knowledge_id: chosen}); }}]);
  }

  /** Сколько областей без данных — коротко; их номера — по «показать», а не сотнями в одном сообщении. */
  function weakSummary(weak) {
    const ids = h('p', {class: 'small', hidden: true}, weak.join(', '));
    const toggle = btn('показать', () => { ids.hidden = !ids.hidden; toggle.textContent = ids.hidden ? 'показать' : 'скрыть'; });
    return h('div', {class: 'alert bad stack'}, h('div', {class: 'row'}, h('span', {}, `Областей без достаточных данных: ${weak.length}. Рецепт не придумывается: `
      + 'удалите или исключите область, выберите настройки её группы или передайте её цвет планировщику. Такие области заштрихованы на картинке.'), toggle), ids);
  }

  function jobView(j) {
    const id = j.id;
    const reload = () => App.render({preserveScroll: true});
    const run = async (op) => { try { await post(`/vector/${id}/edit`, op); reload(); } catch (e) { fail(e); } };
    const selected = new Set();
    const size = j.document.size_mm;
    const exp = j.experiment || {};
    // the tolerance of the outline and the ΔE threshold are two forms of one box each: a wrong number is refused here with its reason beside the box and stays
    // in it; a refusal of the server stands under the box too (ux-save-feedback-p0, REQ-003)
    const toleranceForm = Forms.create(), thresholdForm = Forms.create();
    const tolerance = toleranceForm.add('tolerance', 'Точность контура', Forms.numberInput(Forms.QUANTITIES.vectorTolerance, {value: j.document.tolerance_mm}),
      {quantity: 'vectorTolerance', required: true});
    const thr = thresholdForm.add('threshold', 'Порог ΔE', Forms.numberInput(Forms.QUANTITIES.deltaE, {value: j.threshold}), {quantity: 'deltaE', required: true});
    const apply = (form, box, op) => async () => {
      const v = form.collect();
      if (!v) return;
      try { await post(`/vector/${id}/edit`, op(v)); reload(); } catch (e) { box.setError((e && e.message) || String(e)); }      // the server's words stand under the box
    };

    // the regions as a short list (DEC-090): a line each — the box for a merge, its colour, status, task, size, group and recipe; the
    // actions on the line; the task, the group and the recipe and prediction under it on a click; pages of 30, so editing stays on a page
    const order = new Map(j.regions.map((r, i) => [r.id, i]));
    const byOrder = (a, b) => order.get(a.id) - order.get(b.id);
    const regions = App.list({id: 'vw.job.regions', items: j.regions, page: 30, key: (r) => r.id,
      row: (r) => [VectorEditor.inRow(h('input', {type: 'checkbox', checked: selected.has(r.id), 'aria-label': 'Выбрать ' + r.id,
          onChange: (ev) => { if (ev.target.checked) selected.add(r.id); else selected.delete(r.id); }})),
        swatch(r.lab), h('strong', {}, r.id), pill(...STATUS[r.status]),
        h('span', {class: 'lst-text muted small'}, [(TASKS.find(([t]) => t === r.task) || [r.task, r.task])[1],
          r.outline === 'closed' ? `${num(r.area_mm2, 2)} мм²` : 'центральная линия', `группа ${r.layer_key}`, r.knowledge_id ? 'K' + r.knowledge_id : 'без рецепта'].join(' · ')),
        r.target_sent ? pill('цвет передан планировщику') : null],
      actions: (r) => [btn('Удалить', () => run({op: 'delete', region: r.id}), 'danger'),
        r.status === 'excluded' ? btn('Вернуть', () => run({op: 'include', region: r.id})) : btn('Исключить (без рецепта)', () => run({op: 'exclude', region: r.id})),
        r.status === 'weak' && r.kind === 'fill' && !r.target_sent ? btn('Планировщику', () => run({op: 'to_designer', region: r.id})) : null],
      details: (r) => {
        const pr = r.prediction;
        const task = h('select', {'aria-label': 'Задача области ' + r.id, style: 'min-width:130px', onChange: (ev) => run({op: 'set_task', region: r.id, task: ev.target.value})},
          TASKS.filter(([t]) => r.outline === 'closed' || t === 'line').map(([t, l]) => h('option', {value: t, selected: t === r.task}, l)));
        const group = h('input', {value: r.layer_key, style: 'min-width:90px;width:90px', 'aria-label': 'Группа настроек области ' + r.id});
        return h('div', {class: 'stack small'},
          h('div', {class: 'toolbar'}, field('Задача', task), field('Группа настроек', group),
            btn('Перенести', () => run({op: 'set_layer', region: r.id, layer_key: group.value}))),
          h('div', {}, r.outline === 'closed' ? `Контур · ${num(r.area_mm2, 2)} мм²` : 'Центральная линия'),
          r.knowledge_id ? h('div', {}, 'Рецепт ', link('/knowledge/' + r.knowledge_id, 'K' + r.knowledge_id), ` · ${MODE[r.mode] || r.mode || 'режим не записан'} · ${params(r.parameters)}`)
            : h('div', {class: 'muted'}, 'Рецепта нет'),
          pr ? h('div', {}, swatch(pr.lab), ` Прогноз (REQ-002): уверенность ${num(pr.confidence)} · ожидаемая ошибка ΔE ${num(pr.expected_delta_e)} · ${stability(pr.stability)}`,
            h('div', {class: 'muted'}, (r.task === 'tonal' ? 'разница светлоты ' : 'ΔE до цвета области ') + num(r.distance) + ' · ошибка совпадения ' + num(r.match_error))) : null,
          r.note ? h('div', {}, I18N.tr(r.note)) : null);
      },
      search: (r) => [r.id, r.layer_key, r.knowledge_id ? 'K' + r.knowledge_id : ''].join(' '),
      filters: [{key: 'status', label: 'Данные', options: Object.entries(STATUS).map(([k, [text]]) => [k, text]), test: (r, v) => r.status === v},
        {key: 'task', label: 'Задача', select: true, options: TASKS, test: (r, v) => r.task === v}],
      sorts: [['order', 'По порядку', byOrder], ['weak', 'Сначала без данных', (a, b) => (WEAK_FIRST[a.status] ?? 9) - (WEAK_FIRST[b.status] ?? 9) || byOrder(a, b)],
        ['area', 'Больше площадь', (a, b) => (b.area_mm2 ?? 0) - (a.area_mm2 ?? 0) || byOrder(a, b)]],
      empty: 'Нет областей под такой выбор.'});

    const groups = j.groups.map((g) => [g.key, g.kind === 'line' ? 'линия' : g.kind ? 'заливка' : '—',
      g.knowledge_id ? h('span', {}, link('/knowledge/' + g.knowledge_id, 'K' + g.knowledge_id), g.chosen ? ' · выбран вручную' : ' · ближайший') : 'нет рецепта',
      g.choice_unavailable ? pill('выбранный рецепт больше не подходит', 'warn') : '', `${g.regions.length}`, `${g.candidates.length}`,
      btn('Выбрать настройки', () => settingsDialog(j, g, run), '', !g.kind)]);

    /** The chain's action for a file: the export card is further down this page, so bring it to the eye and put the cursor on its action. */
    const toFile = () => {
      const card = document.getElementById('vw-job-export');
      if (!card) return;
      if (card.scrollIntoView) card.scrollIntoView({block: 'start'});
      const action = [...card.querySelectorAll('button')].find((b) => b.textContent === 'Скачать LightBurn');
      if (action && !action.disabled) action.focus();
    };

    /** A blocker names a region: open it in the list of regions, scrolled into view and focused, so that the fix is one step away. */
    const openTarget = async (b) => {
      if (!b.target || b.target.kind !== 'region') return;
      await regions.open(b.target.id);
      const row = [...regions.el.querySelectorAll('.lst-row')].find((r) => r.getAttribute('data-key') === b.target.id);
      if (row && row.scrollIntoView) row.scrollIntoView({block: 'center'});
      const main = row && row.querySelector('.lst-main');
      if (main && main.focus) main.focus();
    };

    // the history of edits as a short list: the newest first, a version a line, «Вернуть эту версию» on the line
    const history = App.list({id: 'vw.job.history', items: j.history.map((e, pos) => ({...e, pos})), key: (e) => String(e.pos),
      row: (e) => [h('strong', {}, `v${e.version}`), h('span', {class: 'lst-text'}, OPS[e.op.op] || e.op.op), h('span', {class: 'muted small'}, e.at.replace('T', ' ').slice(0, 16))],
      actions: (e) => (DOCUMENT_OPS.includes(e.op.op) && e.version !== j.document.version ? [btn('Вернуть эту версию', () => run({op: 'revert', version: e.version}))] : []),
      search: (e) => `v${e.version} ${OPS[e.op.op] || e.op.op}`,
      sorts: [['new', 'Сначала новые', (a, b) => b.pos - a.pos], ['old', 'Сначала старые', (a, b) => a.pos - b.pos]], empty: 'Правок пока нет'});

    const heading = h('h2', {}, 'Векторная работа · ' + j.name);
    const pencil = VectorWorkspace.renameButton(j.id, j.name, (stored) => { j.name = stored; fill(heading, 'Векторная работа · ' + stored); });
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('div', {class: 'vw-name-row'}, heading, pencil),
        h('p', {class: 'sub'}, `Версия документа ${j.document.version} · ${num(size.width, 1)} × ${num(size.height, 1)} мм · порог ΔE ${j.threshold}`)),
        h('span', {class: 'spacer'}), link('/plans/' + id, 'План гравировки'), link(`/designer?device=${j.device_id}&lens=${App.lensParam(j.lens_id)}`, 'Цели экспериментов')),
      h('div', {class: 'card'}, Lifecycle.chain(j.lifecycle, {onAction: toFile})),
      h('div', {class: 'card stack'}, facts([['Идентификатор', j.plan_identifier], ['Лазер', exp.device && (exp.device.title || exp.device.name)],
        ['Линза', j.lens ? App.lensLabel(j.lens) : 'неизвестна'], ['Титан', exp.material && material(exp.material)],
        ['Стратегия', STRATEGY_NAME[j.document.strategy] || j.document.strategy],
        ['Задача работы', j.engraving_task ? Tasks.name(j.engraving_task.kind) + (j.engraving_task.basis === 'explicit' ? '' : ' · по стратегии') : '—'],
        ['Чистка', j.clean_layer ? 'первый слой C00' : 'нет'], ['Маркеры', j.markers_enabled ? 'включены' : 'выключены'],
        ['Слоёв LightBurn', `${j.layers.length} из ${j.layer_cap} доступных`]])),
      h('div', {class: 'card stack'}, h('h3', {}, 'Изображение и контуры'), h('div', {class: 'grid g2'},
        h('figure', {}, h('img', {src: `/api/plans/${id}/source-image`, style: 'width:100%', alt: 'Исходное изображение'}), h('figcaption', {class: 'muted small'}, 'Исходное изображение')),
        h('figure', {}, h('img', {src: svgSrc(j.svg), style: 'width:100%;background:#fff', alt: 'Векторные контуры'}),
          h('figcaption', {class: 'muted small'}, 'Контуры в цветах изображения; области без достаточных данных заштрихованы красным')))),
      h('div', {class: 'card toolbar'}, tolerance, btn('Применить точность', apply(toleranceForm, tolerance, (v) => ({op: 'set_tolerance', tolerance_mm: v.tolerance}))),
        thr, btn('Применить порог', apply(thresholdForm, thr, (v) => ({op: 'set_threshold', threshold: v.threshold}))), toleranceForm.error, thresholdForm.error,
        btn('Объединить выбранные', () => (selected.size === 2 ? run({op: 'merge', regions: [...selected]}) : fail(new Error('Выберите ровно две области')))),
        btn(j.markers_enabled ? 'Выключить маркеры' : 'Включить маркеры', async () => { try { await put(`/plans/${id}/markers`, {enabled: !j.markers_enabled}); reload(); } catch (e) { fail(e); } })),
      j.weak.length ? weakSummary(j.weak) : null,
      h('div', {class: 'card'}, h('h3', {}, `Области: ${j.regions.length}`),
        regions.el),
      h('div', {class: 'card'}, h('h3', {}, 'Группы настроек'), h('p', {class: 'muted small'}, 'Одна группа — один рецепт; одинаковые рецепты разных групп выводятся в один слой LightBurn.'),
        table(['Группа', 'Нужно', 'Рецепт', '', 'Областей', 'Подходящих рецептов', ''], groups)),
      h('div', {class: 'card stack', id: 'vw-job-export'}, h('h3', {}, 'Экспорт'),
        // REQ-020: задача, для которой будет измерено фото слоя; слой со смешанными задачами измеряется по своему режиму LightBurn
        Lifecycle.exportCard(j.lifecycle, {path: `/vector/${id}/export.lbrn2`, name: 'vector.lbrn2', reload, onTarget: openTarget, withChain: false,
          designer: `/designer?device=${j.device_id}&lens=${App.lensParam(j.lens_id)}`,
          recipe: table(['Слой', 'Режим', 'Задача', 'Областей', 'Прогнозный цвет', 'Уверенность · ошибка'], j.layers.map((l) => [`C${String(l.index).padStart(2, '0')} · ${l.name}`, MODE[l.mode] || l.mode || '—',
            l.task ? Tasks.name(l.task) : h('span', {class: 'muted small'}, 'смешанная: ' + (l.region_tasks || []).map((t) => (TASKS.find(([k]) => k === t) || [t, t])[1]).join(', ') + ' — по слою LightBurn'),
            `${l.region_ids.length}`, h('span', {}, swatch(l.prediction.lab), labText(l.prediction.lab)), `${num(l.prediction.confidence)} · ΔE ${num(l.prediction.expected_delta_e)}`]), 'Слоёв нет')})),
      h('div', {class: 'card'}, h('h3', {}, 'История правок'), history.el));
  }

  const duration = (s) => (s == null ? '—' : s >= 3600 ? `${Math.floor(s / 3600)} ч ${String(Math.round(s % 3600 / 60)).padStart(2, '0')} мин`
    : s >= 60 ? `${Math.floor(s / 60)} мин ${String(Math.round(s % 60)).padStart(2, '0')} с` : `${Math.round(s)} с`);

  /** Вкладка «Файл»: оценка времени всей работы до экспорта, слои с рецептами, экспорт и сохранённые файлы (REQ-042, REQ-043).
      Почему файл пока не создаётся, сказано здесь же, рядом с кнопкой. Слои и файлы идут строками: вкладка узкая. */
  function photoExport(j, refresh, onTarget) {
    const t = j.time, zones = j.zones || [];
    const layers = t.layers.map((row) => {
      const layer = j.layers.find((l) => l.index === row.index), zone = layer ? null : zones.find((z) => z.index === row.index);
      const part = layer || zone;                                       // ни слой цвета, ни фотозона — чистка
      return h('div', {class: 'vw-line'}, h('span', {}, `C${String(row.index).padStart(2, '0')} `,
        layer ? h('span', {class: 'sw', style: `background:rgb(${layer.srgb.join(',')})`}) : zone && zone.picture ? h('img', {class: 'vw-ed-zone-chip', src: zone.picture, alt: ''}) : null,
        layer ? layer.name : zone ? `Фотозона ${zone.number}: ${VectorPhoto.kindName(zone.kind)}` : 'Чистка (перекрёстная заливка)'),
        h('span', {class: 'muted small'}, [part ? `областей ${layer ? layer.region_count : zone.regions.length}` : 'вся работа', part ? `${num(part.area_mm2 / 100, 2)} см²` : null,
          row.seconds == null ? I18N.tr(row.note) : duration(row.seconds)].filter(Boolean).join(' · ')));
    });
    const estimate = h('p', {}, h('strong', {}, `Оценка времени всей работы: ${duration(t.seconds)}`), t.complete ? '' : ' (без слоёв, время которых не оценить)',
      h('span', {class: 'muted small'}, ' — оценка по скорости, шагу строк, проходам и перекрёстной заливке каждого рецепта; переходы между областями не учтены.'));
    const recipe = h('div', {class: 'stack'}, estimate, h('div', {class: 'vw-lines'}, layers),
      h('p', {class: 'small'}, `Слоёв цвета: ${j.layers.length}` + (zones.length ? `, фотозон: ${zones.length}` : '') + ` из ${j.layer_cap}: C00 — чистка`
        + (j.markers_enabled ? ', C01 — маркеры' : '') + '; каждый слой — один рецепт со всеми настройками'
        + (zones.length ? '; фотозоны — слои изображения после слоёв цвета, прозрачные вне своих областей.' : '.')));
    return h('div', {class: 'stack'}, Lifecycle.exportCard(j.lifecycle, {path: `/vector/${j.id}/export.lbrn2`, name: 'vector.lbrn2', reload: refresh, onTarget, recipe,
      withChain: false, recipeLabel: `Полный рецепт и слои (${t.layers.length})`,
      designer: `/designer?device=${j.device_id}&lens=${App.lensParam(j.lens_id)}`}));
  }

  /** Работа из фотографии на один экран (REQ-042, REQ-044, REQ-054): слева вкладки «Разбиение», «Цвета», «AI» и «Файл», посередине
      картинка редактора, справа его панель. Действие с раскраской возвращает работу целиком, и экран обновляется на месте, без
      перерисовки: редактор сохраняет масштаб, инструмент и выделение. Действия уходят на сервер по одному, в том порядке, в
      каком их сделал оператор. */
  function photoView(j, accepted) {
    const reload = () => App.render({preserveScroll: true});
    const exp = j.experiment || {};
    const about = h('div', {class: 'stack'}), split = h('div', {}), file = h('div', {}), review = h('div', {class: 'stack'});
    let shown = null, queue = Promise.resolve(), parts = null, frame = null;
    /** «Размер…» (REQ-001 фичи work-size-and-splitting-a-region-again): в той же очереди; ответ — работа целиком или null при отказе. */
    const resize = (body) => (queue = queue.then(async () => { try { const work = await post(`/vector/${j.id}/size`, body); show(work); return work; } catch (e) { fail(e); return null; } }));
    const head = VectorWorkspace.header(j, {file: () => frame.select('file'), renamed: (name) => { shown = {...shown, name}; head.update(shown); }, resize});
    // feature electron, REQ-085: a work pinned to a laboratory release shows its source under the head; a confirmed step returns the whole work
    const banner = LabSource.banner(`/vector/${j.id}`, 'vector', (work) => show(work));
    const applic = h('div', {});                                      // how far the preview can be trusted at this size (ux-evidence-summaries-p0)
    const evidence = h('div', {class: 'small'});
    const chainBox = h('div', {class: 'vw-chain'});                  // the path of the work's file: prepared, file received, result added, checked
    const summaryBox = h('div', {});                                  // what an accepted result did to the work, when the operator came back from accepting it
    const status = Lifecycle.strip({chain: chainBox, forecast: applic, preview: evidence});    // the three above as one fold on a narrow screen (ux-accessible-layout-p0)
    function show(next) {
      const resplit = !shown || next.document.version !== shown.document.version;
      shown = next;
      head.update(next);
      fill(chainBox, Lifecycle.chain(next.lifecycle, {onAction: (a) => frame.select(a.code === 'compare' ? 'review' : 'file')}));
      banner.update(next);
      fill(applic, EvidenceSummary.applicability(next.applicability));
      const p = next.preview_evidence;
      evidence.className = 'small' + (p && (p.estimated_layers || p.estimated_zones || p.ramp_only_zones) ? ' alert warn' : ' muted');
      fill(evidence, !p ? null : p.ramp_only_zones
        ? `Расчётный вид: ${p.ramp_only_zones} фотозон рассчитаны по тестовым шкалам. В базе для этих режимов нет измерений фотогравировки; точность её цвета и контраста не подтверждена.`
        : p.estimated_layers || p.estimated_zones
        ? `Превью: для ${p.estimated_layers} из ${p.layers} цветовых слоёв и ${p.estimated_zones || 0} фотозон использованы измерения другой ширины. Точность для этой работы не проверена.`
        : `Превью: цвета ${p.layers} слоёв измерены при этом размере. Фотозоны проверяются по своим шкалам.`);
      fill(about, h('details', {class: 'vw-details'}, h('summary', {}, 'Параметры работы'), facts([['Идентификатор', next.plan_identifier], ['Лазер', exp.device && (exp.device.title || exp.device.name)],
        ['Линза', next.lens ? App.lensLabel(next.lens) : 'неизвестна'], ['Титан', exp.material && material(exp.material)],
        ['Измерения', next.source && next.source.kind === 'release' ? `лаборатория ${next.source.lab_name}` : 'этой мастерской'],      // the work's own, whatever the workshop chooses next
        ['Чистка', 'первый слой C00'], ['Маркеры', next.markers_enabled ? 'включены (C01)' : 'выключены'],
        ['Слоёв цвета', `${next.layers.length}` + ((next.zones || []).length ? ` и фотозон ${next.zones.length}` : '') + ` из ${next.layer_cap} доступных`]]),
        h('div', {class: 'row'}, btn(next.markers_enabled ? 'Выключить маркеры' : 'Включить маркеры', async () => {
          try { await put(`/plans/${next.id}/markers`, {enabled: !next.markers_enabled}); await refresh(); } catch (e) { fail(e); }
        }))));
      if (resplit) fill(split, VectorSplit.card(next, reload, smooth));     // счётчики разбиения меняются только с его версией
      fill(file, photoExport(next, refresh, () => frame.select('colours')));
      fill(review, VectorReview.view(next, run));
      status.sync();
      if (parts) parts.update(next);
    }
    async function send(op) {
      try { show(await post(`/vector/${j.id}/colouring`, op)); return true; } catch (e) { fail(e); return false; }
    }
    const run = (op) => (queue = queue.then(() => send(op)));
    /** Ползунок гладкости: в той же очереди, что и действия редактора; границы перерисовываются, цвета остаются (REQ-052). */
    const smooth = (mm) => (queue = queue.then(async () => { try { show(await post(`/vector/${j.id}/smoothing`, {mm})); } catch (e) { fail(e); } }));
    /** Разрешение отправить уменьшенное фото AI (DEC-084): работа его помнит; в той же очереди, цвета не меняются. */
    const permit = (allowed) => (queue = queue.then(async () => { try { show(await post(`/vector/${j.id}/ai-photo`, {allowed})); } catch (e) { fail(e); } }));
    async function refresh() {
      try { show(await get('/vector/' + j.id)); } catch (e) { fail(e); }
    }
    show(j);
    parts = VectorColours.parts(j, run, permit);
    frame = VectorWorkspace.frame({head: [head.el, status.el, summaryBox, banner.el], editor: parts.editor, initial: 'colours', items: [
      ['split', 'Разбиение', split], ['colours', 'Цвета', parts.colours], ['ai', 'AI', parts.ai], ['variants', 'Варианты', parts.variants],
      ['review', VectorReview.tabLabel(j), review], ['file', 'Файл', h('div', {class: 'stack'}, file, about)]]});
    if (accepted) {                                                   // back from accepting a result: what it did to this work (kept in the work, so it is told again)
      get(`/pairs/${accepted}/work-summary`).then((found) => {
        fill(summaryBox, Lifecycle.summary(found, {onNext: () => frame.select('review'), onClose: () => fill(summaryBox)}));
      }).catch(() => fill(summaryBox, h('p', {class: 'muted small'}, 'Итог принятого результата не найден: возможно, фотография удалена.')));
    }
    return frame.el;
  }

  App.register({id: 'vector', async render(ctx) {
    if (ctx.query.plan) {
      const j = await get('/vector/' + ctx.query.plan);
      return j.strategy === 'photo' ? photoView(j, ctx.query.accepted) : jobView(j);
    }
    if (!ctx.query.new) return VectorWorkspace.list();
    if (!ctx.query.classic) return Creation.render(ctx);             // ux-work-creation-p0: the three-step creation; the one-page form stays at &classic=1 (text and a task of its own)
    const [lists, stocks] = await Promise.all([App.hardwareLists(), MaterialPicker.total()]);       // only whether any record exists, not all of them
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер'), link('/devices', 'Лазеры'));
    if (!stocks) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте заготовку титана'), link('/setup', 'Настройки'));
    const start = await App.contextStart(ctx.query);                // the laser, lens and titanium the workshop chose last; the address wins
    return startForm(lists, {...ctx, start, query: {...ctx.query, ...(start.device != null ? {device: start.device, lens: start.lens ?? ctx.query.lens} : {})}});
  }});
})();
