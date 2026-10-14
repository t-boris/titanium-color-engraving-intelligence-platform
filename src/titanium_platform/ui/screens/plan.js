/* План гравировки и экспорт (REQ-012, REQ-013): слои с параметрами и оценками, маркеры, экспорт в LightBurn. */
'use strict';
(() => {
  const {h, btn, link, pill, get, put, del, toast, fail, go, confirmBox, table, num, labText, swatch, facts} = App;
  const MODE = {'Calibration plate': 'Калибровочная плата', 'Discrete color engraving': 'Цветная гравировка', 'Tonal photo engraving': 'Тональная фотогравировка',
    'Color-path photo engraving': 'Фотогравировка по цветовому пути', 'Restored from file': 'Восстановленный из файла'};
  const STATUS = {Draft: 'Черновик', 'Ready to export': 'Готов к экспорту', Exported: 'Экспортирован'};
  const STAGE = {measured: 'Измерено', candidate: 'Кандидат', repeated: 'Повторено', validated: 'Валидировано', production: 'Производственное'};

  function layerRows(p) {
    return p.layers.map((l) => {
      const pr = l.prediction;
      return [l.name, `${num(l.parameters.power, 1)} % · ${num(l.parameters.frequency, 0)} кГц · ${num(l.parameters.speed, 0)} мм/с`,
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
      ev.currentTarget.disabled = true;
      try { await download(p); toast('Файл подготовлен и скачан. Откройте его в LightBurn и проверьте слои', 'ok'); App.render(); } catch (e) { fail(e); ev.currentTarget.disabled = false; }
    }, 'primary', draft || !p.layers.length);
    const warnings = (p.warnings || []).map((w) => h('div', {class: 'alert warn'}, [h('strong', {}, 'Используются производственные параметры под вопросом. '), 'В тональном режиме отдельное подтверждение не требуется. ',
      link('/knowledge/' + w.knowledge_ids[0], 'Посмотреть наблюдения')]));
    const markers = p.markers_enabled ? 'включены' : 'выключены';
    const toggle = p.mode === 'Calibration plate' ? null : btn(p.markers_enabled ? 'Выключить регистрационные маркеры' : 'Включить регистрационные маркеры', async () => {
      try { await put(`/plans/${p.id}/markers`, {enabled: !p.markers_enabled}); App.render(); } catch (e) { fail(e); }
    });
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, p.name), h('p', {class: 'sub'}, `${MODE[p.mode] || p.mode} · ${STATUS[p.status] || p.status}`)), h('span', {class: 'spacer'}), link('/experiments', 'К экспериментам'),
        editRoute ? link(editRoute, 'Редактировать преобразование') : null,
        btn('Удалить план', () => confirmBox('Удалить план', 'Действие необратимо. План, связанный с сохранёнными парами, удалить нельзя.', 'Удалить', async () => { await del('/plans/' + p.id); toast('Запись удалена', 'ok'); go('/experiments'); }), 'danger')),
      draft ? h('div', {class: 'alert warn'}, 'План требует завершения преобразования: экспорт недоступен.') : null, ...warnings,
      h('div', {class: 'card stack'}, facts([['Идентификатор', p.plan_identifier], ['Полос', p.band_count], ['Размер, мм', p.size_mm ? `${num(p.size_mm.width, 1)} × ${num(p.size_mm.height, 1)}` : null],
        ['Регистрационные маркеры', markers + (p.mode === 'Calibration plate' ? ' (обязательны для плат)' : '')]]), h('div', {class: 'row'}, toggle, exportBtn)),
      h('div', {class: 'card'}, h('h3', {}, 'Слои и параметры'), p.layers.length ? table(['Слой', 'Параметры', 'Прогнозный цвет', 'Уверенность', 'Ожидаемая ошибка ΔE', 'Стабильность', 'Стадия', 'Областей'], layerRows(p)) : h('p', {class: 'muted'}, 'Слоёв нет: экспорт недоступен.')),
      h('div', {class: 'card'}, h('h3', {}, 'Результат гравировки'), h('p', {class: 'muted small'}, 'После гравировки сфотографируйте работу на стенде и добавьте пару «файл LightBurn + фотография». Экспорт автоматически не принимается как использованный файл.'),
        link('/ingest?plan=' + p.id, 'Добавить результат гравировки')));
  }});
})();
