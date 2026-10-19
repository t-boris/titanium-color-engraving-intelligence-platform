/* План гравировки и экспорт (REQ-012, REQ-013): слои с параметрами и оценками, картина полос, маркеры, экспорт в LightBurn.
   Слой из записи знания показывает её режим и настройки LightBurn: экспорт пишет рецепт целиком. */
'use strict';
(() => {
  const {h, btn, link, pill, get, put, del, toast, fail, go, confirmBox, table, num, labText, swatch, facts} = App;
  const MODE = {'Calibration plate': 'Калибровочная матрица', 'Laser capability test': 'Тест возможностей лазера', 'Discrete color engraving': 'Цветная гравировка', 'Tonal photo engraving': 'Тональная фотогравировка',
    'Color-path photo engraving': 'Фотогравировка по цветовому пути', 'Restored from file': 'Восстановленный из файла', 'Vector job': 'Векторная работа'};
  const PICTURED = ['Discrete color engraving', 'Tonal photo engraving', 'Color-path photo engraving'];
  const STATUS = {Draft: 'Черновик', 'Ready to export': 'Готов к экспорту', Exported: 'Экспортирован',
    Superseded: 'Заменён новым тестом', Cancelled: 'Отменён', Restored: 'Запись выполненного задания'};
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
      const recipe = l.parameters.layer_type != null;           // запись знания: режим и настройки LightBurn — из её файла
      const s = l.lightburn_settings || p.lightburn_settings || (recipe ? l.parameters : {});
      const mode = l.cut_type || l.parameters.layer_type;
      const offset = mode === 'OffsetFill' || mode === 'Offset Fill';
      const hatch = s.cross_hatch ? 'cross-hatch' : s.bidirectional === false ? 'однонаправленно' : 'двунаправленно';
      const interval = mode === 'Cut' && l.parameters.line_interval == null ? 'шаг заливки не применяется' : `шаг заливки ${num(l.parameters.line_interval, 4)} мм`;
      const engravingMode = mode === 'Cut' ? 'Векторная линия (режим Line)' : offset ? 'Заливка по контуру (Offset Fill)' : `Заливка: ${hatch}`;
      const wobble = s.wobble_enabled ? `Wobble: диаметр ${num(s.wobble_size, 3)} мм · шаг ${num(s.wobble_step, 3)} мм`
        : s.wobble_size === 0 ? 'Wobble: выкл.' : '';
      return [l.name, h('span', {}, `${num(l.parameters.power, 1)} % · ${num(l.parameters.frequency, 1)} кГц · ${num(l.parameters.speed, 0)} мм/с · Q-Pulse ${num(l.parameters.pulse_width, 0)} нс · ${interval} · ${l.parameters.passes} проход(а)`,
        h('div', {class: 'muted small'}, engravingMode, offset ? '' : `, угол ${s.scan_angle ?? 0}°, приращение ${s.angle_increment ?? 0}°`, `, глобальных проходов ${s.global_passes ?? 1}`, wobble ? ` · ${wobble}` : '',
          recipe ? ' · остальные настройки LightBurn — как в измеренном файле' : ''), operating(l)),
        pr ? h('span', {}, swatch(pr.lab), labText(pr.lab)) : '—', pr ? num(pr.confidence) : '—', pr ? num(pr.expected_delta_e) : '—',
        pr ? (pr.stability.assessed ? 'дисперсия ' + num(pr.stability.variance) : 'не оценена') : '—',
        l.stage ? h('span', {}, STAGE[l.stage], l.questioned ? [' ', pill('под вопросом', 'bad')] : '') : '—', l.region_ids ? l.region_ids.length : l.region_count];
    });
  }

  /** Исходное изображение рядом с картиной полос в прогнозных цветах (REQ-012): то, что будет выгравировано, видно до экспорта. */
  function banding(p) {
    if (!PICTURED.includes(p.mode)) return null;
    const discrete = p.mode === 'Discrete color engraving';
    return h('div', {class: 'card stack'}, h('h3', {}, discrete ? 'Цвета плана' : `Полосы плана: ${p.band_count}`),
      h('div', {class: 'grid g2'},
        h('figure', {}, h('img', {src: `/api/plans/${p.id}/source-image`, style: 'width:100%', alt: 'Исходное изображение'}), h('figcaption', {class: 'muted small'}, 'Исходное изображение')),
        h('figure', {}, h('img', {src: `/api/plans/${p.id}/banding.png`, style: 'width:100%;image-rendering:pixelated', alt: discrete ? 'Цвета плана' : 'Полосы в прогнозных цветах'}),
          h('figcaption', {class: 'muted small'}, discrete ? 'Сопоставленные цвета титана; недостижимые заштрихованы красным, исключённые — белые'
            : 'Каждая полоса — в прогнозном цвете её измеренного набора параметров'))));
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
    const vector = p.mode === 'Vector job';
    // a plan restored from an imported file records the job that was engraved: never exported, nothing to add to it (REQ-005)
    const restored = p.mode === 'Restored from file';
    const [editRoute, editLabel] = p.mode === 'Discrete color engraving' ? ['/artwork?plan=' + p.id, 'Редактировать преобразование']
      : p.mode.includes('photo engraving') ? ['/photo?plan=' + p.id, 'Исправить: новый план из этого'] : vector ? ['/vector?plan=' + p.id, 'Открыть векторную работу'] : [null, null];
    const exportBtn = btn('Экспортировать в LightBurn', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await download(p); toast('Файл подготовлен и скачан. Откройте его в LightBurn и проверьте слои', 'ok'); App.render(); } catch (e) { fail(e); self.disabled = false; }
    }, 'primary', draft || ['Superseded', 'Cancelled'].includes(p.status) || !p.layers.length);
    if (restored) exportBtn.hidden = true;
    const warnings = (p.warnings || []).map((w) => PhotoForm.questionedWarning(w));
    const markers = p.markers_enabled ? 'включены' : 'выключены';
    const toggle = ['Calibration plate', 'Laser capability test', 'Restored from file'].includes(p.mode) ? null : btn(p.markers_enabled ? 'Выключить регистрационные маркеры' : 'Включить регистрационные маркеры', async () => {
      try { await put(`/plans/${p.id}/markers`, {enabled: !p.markers_enabled}); App.render(); } catch (e) { fail(e); }
    });
    const exp = p.experiment || {};
    const mat = exp.material || {};
    const materialLabel = [mat.name, mat.grade, mat.batch && `партия ${mat.batch}`].filter(Boolean).join(' · ');
    // REQ-018: an unknown work field leaves the placement unchecked, and the plate says so
    const field = p.work_field || (exp.summary || {}).work_field;
    const fieldLabel = !field ? null : field.checked ? `помещается: ${num(field.needed_mm.width, 0)} × ${num(field.needed_mm.height, 0)} мм в поле ${num(field.field_mm.width, 0)} × ${num(field.field_mm.height, 0)} мм`
      : 'поле линзы неизвестно — размещение не проверено';
    const clean = p.clean_layer;
    const cleanLabel = clean ? `${num(clean.power, 1)} % · ${num(clean.frequency, 0)} кГц · ${num(clean.speed, 0)} мм/с · Q-Pulse ${num(clean.pulse_width, 0)} нс · шаг ${num(clean.interval ?? clean.line_interval, 3)} мм · ${clean.passes ?? 1} проход · ${clean.cross_hatch ? 'перекрестная заливка' : clean.bidirectional ? 'двунаправленная заливка' : 'однонаправленная заливка'}` : 'C00 — первый слой LightBurn';
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, I18N.name(p.name)), h('p', {class: 'sub'}, `${MODE[p.mode] || p.mode} · ${STATUS[p.status] || p.status}`)), h('span', {class: 'spacer'}), restored ? link('/ingest?pair=' + p.restored.pair_id, 'К фотографии работы') : link('/experiment/plan-' + p.id, 'К эксперименту'),
        editRoute ? link(editRoute, editLabel) : null,
        btn('Удалить тест', () => confirmBox('Удалить тест', p.active_pairs
          ? `Удалить плату вместе с проверками (${p.active_pairs})? Загруженные копии RAW и LightBurn будут удалены. История измерений останется, но перестанет влиять на рекомендации.`
          : 'Плата исчезнет из списка экспериментов. История измерений сохранится.', 'Удалить тест', async () => {
            // each check leaves active use on its own (its knowledge is rebuilt); then the plan has only archived checks (DEC-047)
            if (p.active_pairs) for (const pair of (await get('/pairs')).filter((x) => x.plan_id === p.id)) await del('/pairs/' + pair.id);
            await del(`/plans/${p.id}`);
            toast('Тест удалён из активных экспериментов', 'ok'); go('/experiments');
          }), 'danger')),
      draft ? h('div', {class: 'alert warn'}, vector ? [p.strategy === 'photo' ? 'В работе есть цвета без цвета титана в допуске: экспорт недоступен. '
        : 'В работе есть области без достаточных данных: экспорт недоступен. ', link('/vector?plan=' + p.id, 'Открыть векторную работу')]
        : 'План требует завершения преобразования: экспорт недоступен.') : null,
      p.revision_of ? h('div', {class: 'alert ok'}, 'Исправление плана ', link('/plans/' + p.revision_of, '№ ' + p.revision_of), '; тот план не изменён.') : null,
      restored ? h('div', {class: 'alert'}, `План восстановлен из импортированного файла «${p.restored.lightburn_name}»: слои, их параметры и геометрия заливки взяты из файла, `
        + 'плановый цвет слоя — прогноз записи знания на момент восстановления (если он был). Это запись выполненного задания, а не новое задание: экспорт недоступен.') : null,
      ['Superseded', 'Cancelled'].includes(p.status) ? h('div', {class: 'alert warn'},
        'Эта плата больше не актуальна для гравировки. Её параметры сохранены в истории исследования.') : null, ...warnings,
      h('div', {class: 'card stack'}, facts([['Идентификатор', p.plan_identifier], ['Полос', p.band_count], ['Размер, мм', p.size_mm ? `${num(p.size_mm.width, 1)} × ${num(p.size_mm.height, 1)}` : null],
        ['Тип платы', exp.test_name], ['Лазер', exp.device?.title || exp.device?.name], ['Линза', exp.lens || p.lens ? App.lensLabel(exp.lens || p.lens) : p.lens_id == null ? 'неизвестна' : null],
        ['Титан', materialLabel], ['Рабочее поле', fieldLabel], ['Чистка — первый слой C00', cleanLabel],
        ['Подписи и маркеры', markers + (['Calibration plate', 'Laser capability test'].includes(p.mode) ? ' · слой C01, ArUco + QR ID' : '')]]),
        exp.test_description ? h('p', {class: 'muted small'}, exp.test_description) : null,
        h('p', {class: 'muted small'}, 'Чистка — первый слой C00. При экспорте файл LightBurn скачивается на компьютер; он не отправляется в лазер автоматически.'),
        h('div', {class: 'row'}, toggle, exportBtn)),
      banding(p),
      h('div', {class: 'card'}, h('h3', {}, 'Слои и параметры'), p.layers.length ? table(['Слой', 'Параметры', 'Прогнозный цвет', 'Уверенность', 'Ожидаемая ошибка ΔE', 'Стабильность', 'Стадия', 'Областей'], layerRows(p)) : h('p', {class: 'muted'}, 'Слоёв нет: экспорт недоступен.')),
      restored ? null : h('div', {class: 'card'}, h('h3', {}, 'Результат гравировки'), h('p', {class: 'muted small'}, 'После гравировки добавьте фактически запущенный файл LightBurn, фотографию RAW и укажите лазер+линзу вместе с использованной заготовкой титана. Маркеры на плате помогают совместить фотографию с файлом.'),
        link('/ingest?plan=' + p.id, 'Добавить результат гравировки')));
  }});
})();
