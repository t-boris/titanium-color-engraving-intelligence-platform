/* Векторная работа (REQ-021, DEC-065): изображение → редактируемые контуры → обычный файл LightBurn, одна связанная запись.
   Каждая группа настроек получает валидированный или производственный рецепт этого лазера, линзы и титана, режим LightBurn
   которого подходит задаче её областей; рецепт никогда не придумывается. Область без достаточных данных заштрихована на
   предпросмотре и указана в списке; пока такие области есть, экспорт недоступен: удалите область, исключите её («без рецепта»:
   она останется в документе, но не попадёт в файл), выберите настройки её группы или передайте её цвет планировщику. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, post, put, form, toast, fail, go, modal, table, num, labText, swatch, facts} = App;
  const STRATEGIES = [['color', 'Цветные области'], ['fill', 'Заливка силуэта'], ['text', 'Текст'], ['line', 'Линии (центральные)']];
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
    const colours = h('input', {type: 'number', step: '1', min: '1', value: 6});
    const titaniumColours = h('input', {type: 'checkbox'});
    const thr = h('input', {type: 'number', step: 'any', min: '0', placeholder: 'из правил'});
    const grey = h('input', {type: 'number', step: '1', min: '0', max: '255', placeholder: 'авто (Оцу)'});
    const tolerance = h('input', {type: 'number', step: 'any', min: '0', value: 0.05});
    const markers = h('input', {type: 'checkbox'}), clean = h('input', {type: 'checkbox', checked: true});
    const info = h('div', {});
    const err = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const show = (m) => { err.textContent = m; err.hidden = !m; };
    let palette = [];

    async function loadPalette() {
      if (!stock.value) return fill(info);
      try { palette = await get(`/vector/palette?${pick.query()}&material_id=${stock.value}`); } catch (e) { palette = []; return fill(info, h('p', {class: 'alert bad'}, e.message)); }
      const lines = palette.filter((e) => e.mode === 'Cut').length;
      fill(info, palette.length
        ? h('p', {class: 'muted small'}, `Рецептов этого лазера, линзы и титана: ${palette.length} (заливка — ${palette.length - lines}, линия — ${lines}). `,
          'Области, для которых рецепта нет, будут отмечены, и их можно передать планировщику экспериментов.')
        : h('div', {class: 'alert warn'}, 'Для этого лазера, линзы и титана нет валидированных или производственных рецептов: все области окажутся без данных. ',
          link(`/designer?${pick.route()}`, 'Планировщик экспериментов')));
    }
    stock.addEventListener('change', loadPalette);

    const submit = btn('Обвести и подобрать настройки', async (ev) => {
      show('');
      if (!img.files[0]) return show('Добавьте изображение для векторной работы');
      const fd = new FormData();
      fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('material_id', stock.value); fd.append('name', name.value);
      fd.append('width_mm', width.value); fd.append('strategy', strategy.value); fd.append('tolerance_mm', tolerance.value);
      fd.append('markers', markers.checked); fd.append('clean', clean.checked); fd.append('image', img.files[0]);
      if (thr.value !== '') fd.append('threshold', thr.value);
      if (grey.value !== '') fd.append('grey_threshold', grey.value);
      if (strategy.value === 'color') {
        if (titaniumColours.checked) {
          if (!palette.length) return show('Нет цветов титана для этого лазера, линзы и титана');
          // белый — фон: иначе каждый пиксель фона достался бы ближайшему цвету титана и слился бы с его областью
          fd.append('palette', JSON.stringify([[255, 255, 255], ...palette.filter((e) => e.mode !== 'Cut').map((e) => e.srgb)]));
        } else fd.append('n_colors', colours.value);
      }
      const self = ev.currentTarget;
      self.disabled = true;
      try { const j = await form('/vector', fd); toast('Векторная работа создана', 'ok'); go('/vector?plan=' + j.id); } catch (e) { show(e.message); self.disabled = false; }
    }, 'primary');
    loadPalette();
    return h('div', {class: 'stack'},
      h('div', {}, h('h2', {}, 'Векторная работа'), h('p', {class: 'sub'}, 'Изображение превращается в контуры с задачей и настройками из измеренных знаний; результат — обычный файл LightBurn.')),
      h('div', {class: 'card stack'}, h('div', {class: 'grid g2'},
        field('Лазер', pick.laser), field('Линза', pick.lens, 'рецепты — измерения этого лазера с этой линзой'),
        field('Титан', stock, 'рецепты, измеренные на другой заготовке, не используются'), field('Изображение', App.filePick(img, 'Выбрать изображение')),
        field('Название работы', name), field('Ширина работы, мм', width),
        field('Стратегия', strategy, 'цветные области — по цветам изображения; заливка, текст и линии — по тёмному силуэту'),
        field('Число цветов', colours, 'только для цветных областей'), field('Порог ΔE', thr, 'пусто — допуск из правил этого лазера с линзой'),
        field('Порог серого', grey, 'для заливки, текста и линий; пусто — автоматически'), field('Точность контура, мм', tolerance, 'наибольшее отклонение упрощённого контура')),
        h('label', {class: 'row'}, titaniumColours, h('span', {}, 'Цвета областей — из палитры титана (рецепты заливки этого лазера, линзы и титана) и белый фон; область фона затем удалите')),
        h('label', {class: 'row'}, clean, h('span', {}, 'Чистка первым слоем (C00)')),
        h('label', {class: 'row'}, markers, h('span', {}, 'Регистрационные маркеры и идентификатор вне изображения')),
        info, err, submit));
  }

  async function download(id) {
    const res = await fetch(`/api/vector/${id}/export.lbrn2`);
    if (!res.ok) { const d = await res.json(); throw new Error(I18N.tr((d.detail || d).error)); }
    const name = decodeURIComponent((res.headers.get('content-disposition') || '').split("UTF-8''")[1] || 'vector.lbrn2');
    const url = URL.createObjectURL(await res.blob());
    const a = h('a', {href: url, download: name});
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
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

  async function jobView(id) {
    const j = await get('/vector/' + id);
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
      try { await download(id); toast('Файл подготовлен, сохранён в работе и скачан. Откройте его в LightBurn и проверьте слои', 'ok'); reload(); } catch (e) { fail(e); self.disabled = false; }
    }, 'primary', !!j.export_blocked);

    const history = [...j.history].reverse().map((e) => [`v${e.version}`, OPS[e.op.op] || e.op.op, e.at.replace('T', ' ').slice(0, 16),
      DOCUMENT_OPS.includes(e.op.op) && e.version !== j.document.version ? btn('Вернуть эту версию', () => run({op: 'revert', version: e.version})) : '']);

    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Векторная работа · ' + j.name),
        h('p', {class: 'sub'}, `Версия документа ${j.document.version} · ${num(size.width, 1)} × ${num(size.height, 1)} мм · порог ΔE ${j.threshold}`)),
        h('span', {class: 'spacer'}), link('/plans/' + id, 'План гравировки'), link(`/designer?device=${j.device_id}&lens=${App.lensParam(j.lens_id)}`, 'Цели экспериментов')),
      h('div', {class: 'card stack'}, facts([['Идентификатор', j.plan_identifier], ['Лазер', exp.device && (exp.device.title || exp.device.name)],
        ['Линза', j.lens ? App.lensLabel(j.lens) : 'неизвестна'], ['Титан', exp.material && material(exp.material)],
        ['Стратегия', (STRATEGIES.find(([s]) => s === j.document.strategy) || [null, j.document.strategy])[1]],
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
      j.weak.length ? h('div', {class: 'alert bad'}, `Областей без достаточных данных: ${j.weak.length} (${j.weak.join(', ')}). Рецепт не придумывается: удалите или исключите область, выберите настройки её группы или передайте её цвет планировщику.`) : null,
      h('div', {class: 'card'}, h('h3', {}, `Области: ${j.regions.length}`),
        table(['', 'Область', 'Задача', 'Группа настроек', 'Рецепт', 'Прогноз (REQ-002)', 'Данные', ''], rows)),
      h('div', {class: 'card'}, h('h3', {}, 'Группы настроек'), h('p', {class: 'muted small'}, 'Одна группа — один рецепт; одинаковые рецепты разных групп выводятся в один слой LightBurn.'),
        table(['Группа', 'Нужно', 'Рецепт', '', 'Областей', 'Подходящих рецептов', ''], groups)),
      h('div', {class: 'card stack'}, h('h3', {}, 'Экспорт'),
        j.export_blocked ? h('div', {class: 'alert warn'}, I18N.tr(j.export_blocked)) : h('p', {class: 'muted small'}, 'Файл сохраняется в работе: фотография гравировки свяжется с ней по идентификатору в заметках файла.'),
        table(['Слой', 'Режим', 'Областей', 'Прогнозный цвет', 'Уверенность · ошибка'], j.layers.map((l) => [`C${String(l.index).padStart(2, '0')} · ${l.name}`, MODE[l.mode] || l.mode || '—',
          `${l.region_ids.length}`, h('span', {}, swatch(l.prediction.lab), labText(l.prediction.lab)), `${num(l.prediction.confidence)} · ΔE ${num(l.prediction.expected_delta_e)}`]), 'Слоёв нет'),
        h('div', {class: 'row'}, exportBtn),
        j.exports.length ? table(['Файл', 'Версия документа', 'Слоёв', 'Областей', 'Когда'], j.exports.map((e) => [
          h('a', {href: `/api/vector/${id}/exports/${e.number}`, download: e.name}, `№ ${e.number} · ${e.name}`), `v${e.document_version}`, `${e.layers}`, `${e.regions}`,
          e.at.replace('T', ' ').slice(0, 16)])) : null),
      h('div', {class: 'card'}, h('h3', {}, 'История правок'), table(['Версия', 'Действие', 'Когда', ''], history)));
  }

  App.register({id: 'vector', async render(ctx) {
    if (ctx.query.plan) return jobView(ctx.query.plan);
    const [lists, materials] = await Promise.all([App.hardwareLists(), get('/materials')]);
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер'), link('/devices', 'Лазеры'));
    if (!materials.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте заготовку титана'), link('/setup', 'Настройки'));
    return startForm(lists, materials, ctx);
  }});
})();
