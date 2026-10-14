/* Формы вкладок «Титан» и «Стенд» и форма нового профиля лазера (REQ-010, REQ-009). */
'use strict';
const SetupForms = (() => {
  const {h, btn, field, post, put, del, toast, fail, confirmBox} = App;
  const val = (el) => el.value.trim();

  function newProfileForm(reload) {
    const name = h('input', {placeholder: 'Например, MOPA 60 Вт'}), pw = h('input', {type: 'number', step: 'any', placeholder: 'нс'});
    const li = h('input', {type: 'number', step: 'any', placeholder: '0.025'}), passes = h('input', {type: 'number', step: '1', value: 1});
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'}, field('Название', name), field('Длительность импульса', pw), field('Интервал линий, мм', li), field('Проходы', passes)),
      btn('Создать профиль', async () => {
        try { const p = await post('/profiles', {name: val(name), pulse_width: +pw.value, line_interval: +li.value, passes: +passes.value}); toast('Профиль создан', 'ok'); reload(p.id); } catch (e) { fail(e); }
      }, 'primary'));
  }

  function materialTab(items, reload) {
    const m = items[0] || {};
    const name = h('input', {value: m.name || ''}), batch = h('input', {value: m.batch || ''});
    return h('div', {class: 'card stack'}, h('h3', {}, 'Титан'),
      h('p', {class: 'muted small'}, 'Материал и партия необязательны: неизвестное значение остаётся «неизвестно» и не мешает приёму наблюдений.'),
      field('Название', name), field('Идентификатор партии или листа', batch, 'необязательно'),
      btn(m.id ? 'Сохранить материал' : 'Создать материал', async () => {
        try {
          const body = {name: val(name), batch: val(batch) || null};
          if (m.id) await put('/materials/' + m.id, body); else await post('/materials', body);
          toast('Материал сохранён', 'ok'); reload();
        } catch (e) { fail(e); }
      }, 'primary'));
  }

  function standTab(items, reload) {
    const s = items[0] || {};
    const f = {name: h('input', {value: s.name || ''}), camera: h('input', {value: s.camera || ''}), lighting: h('input', {value: s.lighting || ''}),
      angle: h('input', {value: s.angle || ''}), reference_chart: h('input', {value: s.reference_chart || 'ColorChecker Classic (24 поля)'})};
    return h('div', {class: 'card stack'}, h('h3', {}, 'Стенд'),
      h('p', {class: 'muted small'}, 'Формат фотографий — RAW. Эталонная карта — ColorChecker Classic (DEC-025); её обнаружение проверено только на тестовых изображениях, а не на реальном снимке со стенда.'),
      h('div', {class: 'grid g2'}, field('Название стенда', f.name), field('Камера и стойка', f.camera), field('Освещение', f.lighting),
        field('Угол съёмки · число или описание', f.angle), field('Эталонная карта', f.reference_chart)),
      h('div', {class: 'row'}, btn(s.id ? 'Сохранить стенд' : 'Создать стенд', async () => {
        const body = Object.fromEntries(Object.entries(f).map(([k, el]) => [k, val(el)]));
        try { if (s.id) await put('/setups/' + s.id, body); else await post('/setups', body); toast('Стенд сохранён', 'ok'); reload(); } catch (e) { fail(e); }
      }, 'primary'), s.id ? btn('Удалить стенд', () => confirmBox('Удалить стенд', 'Действие необратимо. Стенд, использованный в сохранённых парах, удалить нельзя.', 'Удалить',
        async () => { await del('/setups/' + s.id); toast('Запись удалена', 'ok'); reload(); }), 'danger') : null));
  }

  return {newProfileForm, materialTab, standTab};
})();
