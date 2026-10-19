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
  const MODE = {Scan: 'заливка (Fill)', Cut: 'линия (Line)', OffsetFill: 'заливка по контуру (Offset Fill)', 'Offset Fill': 'заливка по контуру (Offset Fill)'};
  const OPS = {trace: 'обводка изображения', set_task: 'задача области', set_layer: 'группа настроек области', delete: 'удаление области',
    merge: 'объединение областей', set_tolerance: 'точность контура', revert: 'возврат к версии', set_settings: 'настройки группы',
    exclude: 'исключение области', include: 'возврат исключённой области', set_threshold: 'порог ΔE', allow_questioned: 'параметры под вопросом',
    to_designer: 'цвет передан планировщику'};
  const DOCUMENT_OPS = ['trace', 'set_task', 'set_layer', 'delete', 'merge', 'set_tolerance', 'revert'];
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 1)} кГц · ${num(p.speed, 0)} мм/с · Q-Pulse ${num(p.pulse_width, 0)} нс`
    + (p.line_interval == null ? '' : ` · шаг ${num(p.line_interval, 3)} мм`) + ` · ${p.passes ?? 1} проход(а)`;
  const stability = (s) => (s.assessed ? 'дисперсия ' + num(s.variance) : 'стабильность не оценена');
  const material = (m) => [m.name, m.grade, m.batch && `партия ${m.batch}`].filter(Boolean).join(' · ');
  const svgSrc = (svg) => 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);

  function startForm(lists, materials, ctx) {
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens, onChange: () => loadPalette()});
    const stock = h('select', {'aria-label': 'Титан'}, materials.map((m) => h('option', {value: m.id}, material(m))));
    const img = h('input', {type: 'file', accept: 'image/*', 'aria-label': 'Изображение'});
    const name = h('input', {placeholder: 'Название работы'}), width = h('input', {type: 'number', step: 'any', min: '0', value: 60});
    const strategy = h('select', {'aria-label': 'Стратегия'}, STRATEGIES.map(([id, label]) => h('option', {value: id}, label)));
    const colours = h('input', {type: 'number', step: '1', min: '2', max: '29', value: 12});
    const detail = h('select', {'aria-label': 'Детальность'}, DETAIL.map(([v, l]) => h('option', {value: v, selected: v === 'medium'}, l)));
    const algorithm = VectorSplit.picker('slic');
    algorithm.hint.setAttribute('style', 'grid-column:1 / -1');
    const faces = h('input', {type: 'checkbox', checked: true});
    const maxTime = h('input', {type: 'number', step: 'any', min: '0', placeholder: 'без предела'});
    const asShot = h('input', {type: 'checkbox'});
    const thr = h('input', {type: 'number', step: 'any', min: '0', placeholder: 'из правил'});
    const grey = h('input', {type: 'number', step: '1', min: '0', max: '255', placeholder: 'авто (Оцу)'});
    const tolerance = h('input', {type: 'number', step: 'any', min: '0', value: 0.08});
    const markers = h('input', {type: 'checkbox'}), clean = h('input', {type: 'checkbox', checked: true});
    // REQ-020: главная задача работы следует из стратегии, пока оператор не выбрал другую; у каждой области — своя задача
    const STRATEGY_TASK = {photo: 'color_image', fill: 'fill', text: 'text', line: 'line'};
    const task = Tasks.chooser(STRATEGY_TASK[strategy.value], {hint: 'главная задача работы; задачу каждой области можно изменить после обводки'});
    const info = h('div', {});
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const show = (m) => { err.textContent = m; err.hidden = !m; };
    // поля фотографии и поля обводки показываются по стратегии; чистка у фотографии всегда первая (DEC-073)
    const photoFields = h('div', {class: 'grid g2'}, field('Алгоритм разбиения', algorithm.select), field('Число цветов', colours, '2–29, с маркерами 2–28: чистка — первый слой'),
      algorithm.hint, field('Детальность', detail, 'крупно — спокойные большие области, детально — мелкие'),
      field('Наибольшее время гравировки, с/см²', maxTime, 'пусто — без предела; медленные цвета автоматика не берёт'),
      h('label', {class: 'row'}, faces, h('span', {}, 'Искать лица: глаза и губы делятся подробнее')),
      h('label', {class: 'row'}, asShot, h('span', {}, 'Включить цвета без привязки (сняты без эталона и без чистого титана)')));
    const traceFields = h('div', {class: 'grid g2'}, field('Порог серого', grey, 'пусто — автоматически'),
      h('label', {class: 'row'}, clean, h('span', {}, 'Чистка первым слоем (C00)')));
    const tolLabel = h('span', {});
    const photo = () => strategy.value === 'photo';
    const switchFields = () => {
      photoFields.hidden = !photo(); traceFields.hidden = photo();
      tolLabel.textContent = photo() ? 'Сглаживание границ, мм' : 'Точность контура, мм';
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
        let p;
        try { p = await get(`/vector-palette?${pick.query()}&material_id=${stock.value}`); } catch (e) { return fill(info, h('p', {class: 'alert bad'}, e.message)); }
        const asShotCount = p.entries.filter((e) => e.basis === 'as-shot').length;
        return fill(info, p.entries.length
          ? h('p', {class: 'muted small'}, `Измеренных цветов заливки этого лазера, линзы и титана: ${p.entries.length}`,
            asShotCount ? `, из них без привязки к эталону: ${asShotCount}` : '', '. Каждому цвету картинки достанется самый быстрый цвет в пределах допуска ΔE.')
          : h('div', {class: 'alert warn'}, 'Для этого лазера, линзы и титана нет измеренных цветов заливки: разбить можно, раскрасить будет нечем.'));
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
    stock.addEventListener('change', loadPalette);

    const submit = btn('Создать работу', async (ev) => {
      show('');
      if (!img.files[0]) return show('Добавьте изображение для векторной работы');
      const fd = new FormData();
      fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('material_id', stock.value); fd.append('name', name.value);
      fd.append('width_mm', width.value); fd.append('strategy', strategy.value); fd.append('tolerance_mm', tolerance.value);
      fd.append('markers', markers.checked); fd.append('image', img.files[0]);
      if (thr.value !== '') fd.append('threshold', thr.value);
      task.append(fd);
      if (photo()) {
        fd.append('n_colors', colours.value); fd.append('algorithm', algorithm.select.value); fd.append('detail', detail.value); fd.append('faces', faces.checked); fd.append('include_as_shot', asShot.checked);
        if (maxTime.value !== '') fd.append('max_time', maxTime.value);
      } else {
        fd.append('clean', clean.checked);
        if (grey.value !== '') fd.append('grey_threshold', grey.value);
      }
      const self = ev.currentTarget;
      self.disabled = true;
      try { const j = await form('/vector', fd); toast('Векторная работа создана', 'ok'); go('/vector?plan=' + j.id); } catch (e) { show(e.message); self.disabled = false; }
    }, 'primary');
    switchFields();
    return h('div', {class: 'stack'},
      h('div', {}, h('h2', {}, 'Векторная работа'), h('p', {class: 'sub'}, 'Фотография делится на цветные области и раскрашивается измеренными цветами титана; заливка, текст и линии обводятся по силуэту. Результат — обычный файл LightBurn.')),
      h('div', {class: 'card stack'}, h('div', {class: 'grid g2'},
        field('Лазер', pick.laser), field('Линза', pick.lens, 'цвета и рецепты — измерения этого лазера с этой линзой'),
        field('Титан', stock, 'цвета, измеренные на другой заготовке, не используются'), field('Изображение', App.filePick(img, 'Выбрать изображение')),
        field('Название работы', name), field('Ширина работы, мм', width),
        field('Стратегия', strategy, 'фото — цветные области по картинке; заливка, текст и линии — по тёмному силуэту'),
        field('Допуск ΔE', thr, 'пусто — допуск из правил этого лазера с линзой; если его нет, задайте здесь'),
        h('label', {class: 'f'}, tolLabel, tolerance)),
        photoFields, traceFields, task.el,
        h('label', {class: 'row'}, markers, h('span', {}, 'Регистрационные маркеры и идентификатор вне изображения')),
        info, err, submit));
  }

  /** Файл с сервера сохраняется на компьютер; ошибка сервера показывается переведённой, без перехода на адрес API. */
  async function download(path, fallbackName) {
    let res;
    try { res = await fetch('/api' + path); } catch (_) { throw new Error('Нет связи с локальным сервисом. Запущено ли приложение?'); }
    if (!res.ok) {
      let raw = null;
      try { const d = await res.json(); raw = (d.detail || d).error; } catch (_) { raw = null; }
      throw new Error(raw ? I18N.tr(raw) : `Ошибка сервера (${res.status}). Файл не получен.`);
    }
    const name = decodeURIComponent((res.headers.get('content-disposition') || '').split("UTF-8''")[1] || fallbackName);
    const url = URL.createObjectURL(await res.blob());
    const a = h('a', {href: url, download: name});
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }
  const saveButton = (path, label, name) => btn(label, async (ev) => {
    const self = ev.currentTarget;
    self.disabled = true;
    try { await download(path, name); } catch (e) { fail(e); } finally { self.disabled = false; }
  });

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
    const tolerance = h('input', {type: 'number', step: 'any', min: '0', value: j.document.tolerance_mm, 'aria-label': 'Точность контура, мм'});
    const thr = h('input', {type: 'number', step: 'any', min: '0', value: j.threshold, 'aria-label': 'Порог ΔE'});

    const rows = j.regions.map((r) => {
      const pr = r.prediction;
      const [label, kind] = STATUS[r.status];
      const task = h('select', {'aria-label': 'Задача области ' + r.id, style: 'min-width:130px', onChange: (ev) => run({op: 'set_task', region: r.id, task: ev.target.value})},
        TASKS.filter(([t]) => r.outline === 'closed' || t === 'line').map(([t, l]) => h('option', {value: t, selected: t === r.task}, l)));
      const group = h('input', {value: r.layer_key, style: 'min-width:90px;width:90px', 'aria-label': 'Группа настроек области ' + r.id});
      return [h('input', {type: 'checkbox', 'aria-label': 'Выбрать ' + r.id, onChange: (ev) => { if (ev.target.checked) selected.add(r.id); else selected.delete(r.id); }}),
        h('span', {}, swatch(r.lab), r.id, h('div', {class: 'muted small'}, r.outline === 'closed' ? `контур · ${num(r.area_mm2, 2)} мм²` : 'центральная линия')),
        task,
        h('span', {class: 'row'}, group, btn('Перенести', () => run({op: 'set_layer', region: r.id, layer_key: group.value}))),
        r.knowledge_id ? h('span', {}, link('/knowledge/' + r.knowledge_id, 'K' + r.knowledge_id), ` · ${MODE[r.mode] || r.mode || 'режим не записан'}`,
          h('div', {class: 'muted small'}, params(r.parameters))) : '—',
        pr ? h('span', {}, swatch(pr.lab), `уверенность ${num(pr.confidence)} · ожидаемая ошибка ΔE ${num(pr.expected_delta_e)} · ${stability(pr.stability)}`,
          h('div', {class: 'muted small'}, (r.task === 'tonal' ? 'разница светлоты ' : 'ΔE до цвета области ') + num(r.distance) + ' · ошибка совпадения ' + num(r.match_error))) : '—',
        h('span', {}, pill(label, kind), r.note ? h('div', {class: 'small'}, I18N.tr(r.note)) : null, r.target_sent ? h('div', {}, pill('цвет передан планировщику')) : null),
        h('span', {class: 'row'}, btn('Удалить', () => run({op: 'delete', region: r.id}), 'danger'),
          r.status === 'excluded' ? btn('Вернуть', () => run({op: 'include', region: r.id})) : btn('Исключить (без рецепта)', () => run({op: 'exclude', region: r.id})),
          r.status === 'weak' && r.kind === 'fill' && !r.target_sent ? btn('Планировщику', () => run({op: 'to_designer', region: r.id})) : null)];
    });

    const groups = j.groups.map((g) => [g.key, g.kind === 'line' ? 'линия' : g.kind ? 'заливка' : '—',
      g.knowledge_id ? h('span', {}, link('/knowledge/' + g.knowledge_id, 'K' + g.knowledge_id), g.chosen ? ' · выбран вручную' : ' · ближайший') : 'нет рецепта',
      g.choice_unavailable ? pill('выбранный рецепт больше не подходит', 'warn') : '', `${g.regions.length}`, `${g.candidates.length}`,
      btn('Выбрать настройки', () => settingsDialog(j, g, run), '', !g.kind)]);

    const exportBtn = btn('Экспортировать в LightBurn', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await download(`/vector/${id}/export.lbrn2`, 'vector.lbrn2'); toast('Файл подготовлен, сохранён в работе и скачан. Откройте его в LightBurn и проверьте слои', 'ok'); reload(); } catch (e) { fail(e); self.disabled = false; }
    }, 'primary', !!j.export_blocked);

    const history = [...j.history].reverse().map((e) => [`v${e.version}`, OPS[e.op.op] || e.op.op, e.at.replace('T', ' ').slice(0, 16),
      DOCUMENT_OPS.includes(e.op.op) && e.version !== j.document.version ? btn('Вернуть эту версию', () => run({op: 'revert', version: e.version})) : '']);

    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Векторная работа · ' + j.name),
        h('p', {class: 'sub'}, `Версия документа ${j.document.version} · ${num(size.width, 1)} × ${num(size.height, 1)} мм · порог ΔE ${j.threshold}`)),
        h('span', {class: 'spacer'}), link('/plans/' + id, 'План гравировки'), link(`/designer?device=${j.device_id}&lens=${App.lensParam(j.lens_id)}`, 'Цели экспериментов')),
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
      h('div', {class: 'card toolbar'}, field('Точность контура, мм', tolerance), btn('Применить точность', () => run({op: 'set_tolerance', tolerance_mm: +tolerance.value})),
        field('Порог ΔE', thr), btn('Применить порог', () => run({op: 'set_threshold', threshold: +thr.value})),
        btn('Объединить выбранные', () => (selected.size === 2 ? run({op: 'merge', regions: [...selected]}) : fail(new Error('Выберите ровно две области')))),
        btn(j.markers_enabled ? 'Выключить маркеры' : 'Включить маркеры', async () => { try { await put(`/plans/${id}/markers`, {enabled: !j.markers_enabled}); reload(); } catch (e) { fail(e); } })),
      j.weak.length ? weakSummary(j.weak) : null,
      h('div', {class: 'card'}, h('h3', {}, `Области: ${j.regions.length}`),
        table(['', 'Область', 'Задача', 'Группа настроек', 'Рецепт', 'Прогноз (REQ-002)', 'Данные', ''], rows)),
      h('div', {class: 'card'}, h('h3', {}, 'Группы настроек'), h('p', {class: 'muted small'}, 'Одна группа — один рецепт; одинаковые рецепты разных групп выводятся в один слой LightBurn.'),
        table(['Группа', 'Нужно', 'Рецепт', '', 'Областей', 'Подходящих рецептов', ''], groups)),
      h('div', {class: 'card stack'}, h('h3', {}, 'Экспорт'),
        j.export_blocked ? h('div', {class: 'alert warn'}, I18N.tr(j.export_blocked)) : h('p', {class: 'muted small'}, 'Файл сохраняется в работе: фотография гравировки свяжется с ней по идентификатору в заметках файла.'),
        // REQ-020: задача, для которой будет измерено фото слоя; слой со смешанными задачами измеряется по своему режиму LightBurn
        table(['Слой', 'Режим', 'Задача', 'Областей', 'Прогнозный цвет', 'Уверенность · ошибка'], j.layers.map((l) => [`C${String(l.index).padStart(2, '0')} · ${l.name}`, MODE[l.mode] || l.mode || '—',
          l.task ? Tasks.name(l.task) : h('span', {class: 'muted small'}, 'смешанная: ' + (l.region_tasks || []).map((t) => (TASKS.find(([k]) => k === t) || [t, t])[1]).join(', ') + ' — по слою LightBurn'),
          `${l.region_ids.length}`, h('span', {}, swatch(l.prediction.lab), labText(l.prediction.lab)), `${num(l.prediction.confidence)} · ΔE ${num(l.prediction.expected_delta_e)}`]), 'Слоёв нет'),
        h('div', {class: 'row'}, exportBtn),
        j.exports.length ? table(['Файл', 'Версия документа', 'Слоёв', 'Областей', 'Когда', ''], j.exports.map((e) => [
          `№ ${e.number} · ${e.name}`, `v${e.document_version}`, `${e.layers}`, `${e.regions}`, e.at.replace('T', ' ').slice(0, 16),
          saveButton(`/vector/${id}/exports/${e.number}`, 'Скачать', e.name)])) : null),
      h('div', {class: 'card'}, h('h3', {}, 'История правок'), table(['Версия', 'Действие', 'Когда', ''], history)));
  }

  const duration = (s) => (s == null ? '—' : s >= 3600 ? `${Math.floor(s / 3600)} ч ${String(Math.round(s % 3600 / 60)).padStart(2, '0')} мин`
    : s >= 60 ? `${Math.floor(s / 60)} мин ${String(Math.round(s % 60)).padStart(2, '0')} с` : `${Math.round(s)} с`);

  /** Шаг «Файл LightBurn»: оценка времени всей работы до экспорта, слои с рецептами, экспорт и сохранённые файлы (REQ-042, REQ-043).
      Почему файл пока не создаётся, сказано здесь же, рядом с кнопкой. */
  function photoExport(j, refresh) {
    const t = j.time;
    const rows = t.layers.map((row) => {
      const layer = j.layers.find((l) => l.index === row.index);
      return [`C${String(row.index).padStart(2, '0')}`, layer ? h('span', {}, h('span', {class: 'sw', style: `background:rgb(${layer.srgb.join(',')})`}), layer.name) : 'Чистка (перекрёстная заливка)',
        layer ? `${layer.region_count}` : 'вся работа', layer ? `${num(layer.area_mm2 / 100, 2)} см²` : '—',
        row.seconds == null ? h('span', {class: 'muted small'}, I18N.tr(row.note)) : duration(row.seconds)];
    });
    const exportBtn = btn('Создать файл LightBurn', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await download(`/vector/${j.id}/export.lbrn2`, 'vector.lbrn2'); toast('Файл создан, сохранён в работе и скачан. Откройте его в LightBurn и проверьте слои', 'ok'); await refresh(); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'primary', !!j.export_blocked);
    return h('div', {class: 'card stack'}, h('h3', {}, '2. Файл LightBurn'),
      h('p', {}, h('strong', {}, `Оценка времени всей работы: ${duration(t.seconds)}`), t.complete ? '' : ' (без слоёв, время которых не оценить)',
        h('span', {class: 'muted small'}, ' — оценка по скорости, шагу строк, проходам и перекрёстной заливке каждого рецепта; переходы между областями не учтены.')),
      table(['Слой', 'Рецепт', 'Областей', 'Площадь', 'Время'], rows),
      h('p', {class: 'small'}, `Слоёв цвета: ${j.layers.length} из ${j.layer_cap}: C00 — чистка` + (j.markers_enabled ? ', C01 — маркеры' : '') + '; каждый слой — один рецепт со всеми настройками.'),
      j.export_blocked ? h('div', {class: 'alert warn'}, I18N.tr(j.export_blocked)) : h('p', {class: 'muted small'}, 'Файл сохраняется в работе вместе с раскраской: фотография гравировки свяжется с ней по идентификатору в заметках файла.'),
      h('div', {class: 'row'}, exportBtn),
      j.exports.length ? table(['Файл', 'Вариант раскраски', 'Слоёв', 'Областей', 'Время', 'Когда', ''], j.exports.map((e) => [`№ ${e.number} · ${e.name}`,
        e.variant ? `№ ${e.variant}` : '—', `${e.layers}`, `${e.regions}`, duration(e.seconds), e.at.replace('T', ' ').slice(0, 16),
        saveButton(`/vector/${j.id}/exports/${e.number}`, 'Скачать', e.name)])) : null);
  }

  /** Работа из фотографии: цвета и разбиение, файл (REQ-042, REQ-044). Действие с раскраской возвращает работу целиком, и
      экран обновляется на месте, без перерисовки: редактор сохраняет масштаб, инструмент и выделение. Действия уходят на
      сервер по одному, в том порядке, в каком их сделал оператор. */
  function photoView(j) {
    const reload = () => App.render({preserveScroll: true});
    const exp = j.experiment || {};
    const head = h('div', {class: 'row'}), about = h('div', {class: 'card stack'}), split = h('div', {}), file = h('div', {});
    let shown = null, queue = Promise.resolve(), colours = null;
    function show(next) {
      const resplit = !shown || next.document.version !== shown.document.version;
      shown = next;
      const size = next.document.size_mm;
      fill(head, h('div', {}, h('h2', {}, 'Векторная работа · ' + next.name),
        h('p', {class: 'sub'}, `Фото: цветные области · ${num(size.width, 1)} × ${num(size.height, 1)} мм · разбиение № ${next.document.version}`)),
        h('span', {class: 'spacer'}), link('/plans/' + next.id, 'План гравировки'));
      fill(about, facts([['Идентификатор', next.plan_identifier], ['Лазер', exp.device && (exp.device.title || exp.device.name)],
        ['Линза', next.lens ? App.lensLabel(next.lens) : 'неизвестна'], ['Титан', exp.material && material(exp.material)],
        ['Чистка', 'первый слой C00'], ['Маркеры', next.markers_enabled ? 'включены (C01)' : 'выключены'],
        ['Слоёв цвета', `${next.layers.length} из ${next.layer_cap} доступных`]]),
        h('div', {class: 'row'}, btn(next.markers_enabled ? 'Выключить маркеры' : 'Включить маркеры', async () => {
          try { await put(`/plans/${next.id}/markers`, {enabled: !next.markers_enabled}); await refresh(); } catch (e) { fail(e); }
        })));
      if (resplit) fill(split, VectorSplit.card(next, reload, smooth));     // счётчики разбиения меняются только с его версией
      fill(file, photoExport(next, refresh));
      if (colours) colours.update(next);
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
    colours = VectorColours.card(j, run, split, permit);
    return h('div', {class: 'stack'}, head, about, colours.el, file);
  }

  App.register({id: 'vector', async render(ctx) {
    if (ctx.query.plan) {
      const j = await get('/vector/' + ctx.query.plan);
      return j.strategy === 'photo' ? photoView(j) : jobView(j);
    }
    const [lists, materials] = await Promise.all([App.hardwareLists(), get('/materials')]);
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер'), link('/devices', 'Лазеры'));
    if (!materials.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте заготовку титана'), link('/setup', 'Настройки'));
    return startForm(lists, materials, ctx);
  }});
})();
