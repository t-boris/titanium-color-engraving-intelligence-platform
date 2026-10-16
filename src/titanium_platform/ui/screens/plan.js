/* План гравировки и экспорт (REQ-012, REQ-013): слои с параметрами и оценками, маркеры, экспорт в LightBurn. */
'use strict';
(() => {
  const {h, btn, link, pill, get, put, del, toast, fail, go, confirmBox, table, num, labText, swatch, facts} = App;
  const MODE = {'Calibration plate': 'Калибровочная матрица', 'Laser capability test': 'Тест возможностей лазера', 'Discrete color engraving': 'Цветная гравировка', 'Tonal photo engraving': 'Тональная фотогравировка',
    'Color-path photo engraving': 'Фотогравировка по цветовому пути', 'Restored from file': 'Восстановленный из файла'};
  const STATUS = {Draft: 'Черновик', 'Ready to export': 'Готов к экспорту', Exported: 'Экспортирован',
    Superseded: 'Заменён новым тестом', Cancelled: 'Отменён'};
  const STAGE = {measured: 'Измерено', candidate: 'Кандидат', repeated: 'Повторено', validated: 'Валидировано', production: 'Производственное'};

  /** Расчёт по паспорту лазера (REQ-017): энергия импульса и предупреждение о частоте ниже среза. Это не измерение. */
  function operating(l) {
    const o = l.operating_point;
    if (!o) return '';
    const energy = o.pulse_energy_mj == null ? '' : ` · ${+o.pulse_energy_mj.toPrecision(3)} мДж`;
    return h('div', {class: 'muted small', title: 'Расчёт по паспорту лазера, не измерение'}, `≈ ${+o.output_power_w.toPrecision(3)} Вт${energy}`,
      o.below_cutoff ? [' ', pill('ниже среза: ' + Math.round(o.power_factor * 100) + ' % мощности', 'warn')] : '');
  }

  function layerRows(p) {
    return p.layers.map((l) => {
      const pr = l.prediction;
      const s = l.lightburn_settings || p.lightburn_settings || {};
      const hatch = s.cross_hatch ? 'cross-hatch' : s.bidirectional === false ? 'однонаправленно' : 'двунаправленно';
      const interval = l.cut_type === 'Cut' ? 'шаг заливки не применяется' : `шаг заливки ${num(l.parameters.line_interval, 4)} мм`;
      const engravingMode = l.cut_type === 'Cut' ? 'Векторная линия (режим Line)' : l.cut_type === 'OffsetFill' ? 'Заливка по контуру (Offset Fill)' : `Заливка: ${hatch}`;
      const wobble = s.wobble_enabled ? `Wobble: диаметр ${num(s.wobble_size, 3)} мм · шаг ${num(s.wobble_step, 3)} мм`
        : s.wobble_size === 0 ? 'Wobble: выкл.' : '';
      return [l.name, h('span', {}, `${num(l.parameters.power, 1)} % · ${num(l.parameters.frequency, 1)} кГц · ${num(l.parameters.speed, 0)} мм/с · Q-Pulse ${num(l.parameters.pulse_width, 0)} нс · ${interval} · ${l.parameters.passes} проход(а)`,
        h('div', {class: 'muted small'}, engravingMode, l.cut_type === 'OffsetFill' ? '' : `, угол ${s.scan_angle ?? 0}°, приращение ${s.angle_increment ?? 0}°`, `, глобальных проходов ${s.global_passes ?? 1}`, wobble ? ` · ${wobble}` : ''), operating(l)),
        pr ? h('span', {}, swatch(pr.lab), labText(pr.lab)) : '—', pr ? num(pr.confidence) : '—', pr ? num(pr.expected_delta_e) : '—',
        pr ? (pr.stability.assessed ? 'дисперсия ' + num(pr.stability.variance) : 'не оценена') : '—',
        l.stage ? h('span', {}, STAGE[l.stage], l.questioned ? [' ', pill('под вопросом', 'bad')] : '') : '—', l.region_count];
    });
  }

  async function download(p) {
    const res = await fetch(`/api/plans/${p.id}/export.lbrn2`);
    if (!res.ok) { const d = await res.json(); throw new Error(I18N.tr((d.detail || d).error)); }
    const url = URL.createObjectURL(await res.blob());
    const a = h('a', {href: url, download: p.name.replace(/[^\w.-]+/g, '_') + '.lbrn2'});
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  App.register({id: 'plan', async render(ctx) {
    let p;
    try { p = await get('/plans/' + ctx.arg); } catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'План гравировки не найден'), link('/experiments', 'К экспериментам')); }
    const draft = p.status === 'Draft';
    const editRoute = p.mode === 'Discrete color engraving' ? '/artwork?plan=' + p.id : p.mode.includes('photo engraving') ? '/photo?plan=' + p.id : null;
    const exportBtn = btn('Экспортировать в LightBurn', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await download(p); toast('Файл подготовлен и скачан. Откройте его в LightBurn и проверьте слои', 'ok'); App.render(); } catch (e) { fail(e); self.disabled = false; }
    }, 'primary', draft || ['Superseded', 'Cancelled'].includes(p.status) || !p.layers.length);
    const warnings = (p.warnings || []).map((w) => h('div', {class: 'alert warn'}, [h('strong', {}, 'Используются производственные параметры под вопросом. '), 'В тональном режиме отдельное подтверждение не требуется. ',
      link('/knowledge/' + w.knowledge_ids[0], 'Посмотреть наблюдения')]));
    const markers = p.markers_enabled ? 'включены' : 'выключены';
    const toggle = ['Calibration plate', 'Laser capability test'].includes(p.mode) ? null : btn(p.markers_enabled ? 'Выключить регистрационные маркеры' : 'Включить регистрационные маркеры', async () => {
      try { await put(`/plans/${p.id}/markers`, {enabled: !p.markers_enabled}); App.render(); } catch (e) { fail(e); }
    });
    const exp = p.experiment || {};
    const mat = exp.material || {};
    const materialLabel = [mat.name, mat.grade, mat.batch && `партия ${mat.batch}`].filter(Boolean).join(' · ');
    const clean = p.clean_layer;
    const cleanLabel = clean ? `${num(clean.power, 1)} % · ${num(clean.frequency, 0)} кГц · ${num(clean.speed, 0)} мм/с · Q-Pulse ${num(clean.pulse_width, 0)} нс · шаг ${num(clean.interval ?? clean.line_interval, 3)} мм · ${clean.passes ?? 1} проход · ${clean.cross_hatch ? 'перекрестная заливка' : clean.bidirectional ? 'двунаправленная заливка' : 'однонаправленная заливка'}` : 'C00 — первый слой LightBurn';
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, p.name), h('p', {class: 'sub'}, `${MODE[p.mode] || p.mode} · ${STATUS[p.status] || p.status}`)), h('span', {class: 'spacer'}), link('/experiments', 'К экспериментам'),
        editRoute ? link(editRoute, 'Редактировать преобразование') : null,
        btn('Удалить тест', () => confirmBox('Удалить тест', p.active_pairs
          ? `Удалить плату вместе с проверками (${p.active_pairs})? Загруженные копии RAW и LightBurn будут удалены. История измерений останется, но перестанет влиять на рекомендации.`
          : 'Плата исчезнет из списка экспериментов. История измерений сохранится.', 'Удалить тест', async () => {
            await del(`/plans/${p.id}${p.active_pairs ? '?with_pairs=true' : ''}`);
            toast('Тест удалён из активных экспериментов', 'ok'); go('/experiments');
          }), 'danger')),
      draft ? h('div', {class: 'alert warn'}, 'План требует завершения преобразования: экспорт недоступен.') : null,
      ['Superseded', 'Cancelled'].includes(p.status) ? h('div', {class: 'alert warn'},
        'Эта плата больше не актуальна для гравировки. Её параметры сохранены в истории исследования.') : null, ...warnings,
      h('div', {class: 'card stack'}, facts([['Идентификатор', p.plan_identifier], ['Полос', p.band_count], ['Размер, мм', p.size_mm ? `${num(p.size_mm.width, 1)} × ${num(p.size_mm.height, 1)}` : null],
        ['Тип платы', exp.test_name], ['Лазер', exp.device?.title || exp.device?.name], ['Линза', exp.lens ? `${exp.lens.name} · ${exp.lens.focal_length_mm} мм` : null],
        ['Титан', materialLabel], ['Чистка — первый слой C00', cleanLabel],
        ['Подписи и маркеры', markers + (['Calibration plate', 'Laser capability test'].includes(p.mode) ? ' · слой C01, ArUco + QR ID' : '')]]),
        exp.test_description ? h('p', {class: 'muted small'}, exp.test_description) : null,
        h('p', {class: 'muted small'}, 'Чистка — первый слой C00. При экспорте файл LightBurn скачивается на компьютер; он не отправляется в лазер автоматически.'),
        h('div', {class: 'row'}, toggle, exportBtn)),
      h('div', {class: 'card'}, h('h3', {}, 'Слои и параметры'), p.layers.length ? table(['Слой', 'Параметры', 'Прогнозный цвет', 'Уверенность', 'Ожидаемая ошибка ΔE', 'Стабильность', 'Стадия', 'Областей'], layerRows(p)) : h('p', {class: 'muted'}, 'Слоёв нет: экспорт недоступен.')),
      h('div', {class: 'card'}, h('h3', {}, 'Результат гравировки'), h('p', {class: 'muted small'}, 'После гравировки добавьте фактически запущенный файл LightBurn, фотографию RAW и укажите лазер+линзу вместе с использованной заготовкой титана. Маркеры на плате помогают совместить фотографию с файлом.'),
        link('/ingest?plan=' + p.id, 'Добавить результат гравировки')));
  }});
})();
