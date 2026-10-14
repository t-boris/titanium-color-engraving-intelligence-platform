/* Вкладка «Линза»: какая линза стоит на лазере, какое пятно и поле она даёт, список линз, замена и новая линза (REQ-019, DEC-041).
   Пятно и поле считает сервер (characterization); здесь только слова и формы. Замена линзы сохраняется сразу. */
'use strict';
const DeviceLens = (() => {
  const {h, btn, field, pill, get, post, put, patch, del, toast, fail, confirmBox, table, facts} = App;
  const val = (el) => el.value.trim();
  const num = (el) => (val(el) === '' ? null : +val(el).replace(',', '.'));
  const g = (v, d = 4) => (v == null ? '—' : String(+(+v).toPrecision(d)));
  const SOURCE = {lens: 'по линзе', 'lens and laser settings': 'меньшее из линзы и настроек лазера', 'Field Size': 'по настройкам: Field Size', 'Size Width / Size Height': 'по настройкам: размер рабочей области'};

  function summary(d) {
    const c = d.characterization, spot = c.items.find((i) => i.key === 'spot_diameter'), lens = d.lens;
    if (!lens) {
      return h('div', {class: 'alert warn'}, 'Линза не установлена: пятно и рабочее поле от неё не рассчитываются. Выберите линзу ниже или создайте новую.');
    }
    const range = spot.low ? `${g(spot.low, 3)}${spot.high ? '–' + g(spot.high, 3) : '+'} мкм (границы, в расчётах не участвуют)` : null;
    const wf = c.work_field_mm;
    return h('div', {class: 'stack'}, facts([['Установлена', `${lens.name} · фокус ${g(lens.focal_length_mm)} мм` + (lens.expansion !== 1 ? ` · расширитель ×${lens.expansion}` : '')],
      ['Диаметр пятна', spot.value != null ? `${g(spot.value, 3)} мкм (${spot.basis === 'measured' ? 'измерено вами' : 'рассчитано'})` : (range || 'не определён')],
      ['Рабочее поле', wf ? `${g(wf.width)} × ${g(wf.height)} мм (${SOURCE[wf.source] || wf.source})` : 'не определено']]),
    spot.waiting_for.includes('m2') ? h('div', {class: 'alert warn'}, 'Нужно M² (качество пучка) из руководства лазера или измеренное пятно. Впишите их на вкладке «Обзор» → «Изменить паспорт».') : null,
    wf && wf.settings_exceeds_lens ? h('div', {class: 'alert warn'}, 'Поле в настройках лазера больше поля линзы: плата ограничена полем линзы.') : null);
  }

  /** Строка линзы: поставить, править, удалить. */
  function lensRow(d, l, refresh) {
    const here = d.lens && d.lens.id === l.id, elsewhere = l.installed_on && !here;
    const set = btn(here ? 'Снять' : 'Поставить', async () => {
      try { await put(`/devices/${d.id}/lens`, {lens_id: here ? null : l.id}); toast(here ? 'Линза снята' : 'Линза установлена', 'ok'); refresh(d.id); } catch (e) { fail(e); }
    }, here ? '' : 'primary', !!elsewhere);
    const remove = btn('Удалить', () => confirmBox('Удалить линзу', `«${l.name}». Установленную линзу удалить нельзя. Старые платы сохранят её описание.`, 'Удалить',
      async () => { await del('/lenses/' + l.id); toast('Линза удалена', 'ok'); refresh(d.id); }), 'danger', here);
    return [h('div', {}, h('strong', {}, l.name), l.note ? h('div', {class: 'small muted'}, l.note) : null), `${g(l.focal_length_mm)} мм`, l.field_mm ? `${g(l.field_mm)} мм` : '—',
      l.expansion === 1 ? '—' : '×' + l.expansion, here ? pill('установлена', 'ok') : elsewhere ? pill('на «' + l.installed_on.name + '»', 'warn') : '', h('span', {class: 'row'}, set, remove)];
  }

  function form(d, refresh) {
    const f = {name: h('input', {placeholder: 'например, F-theta 254', 'aria-label': 'Название линзы'}), focal: h('input', {type: 'number', step: 'any', placeholder: 'мм', 'aria-label': 'Фокусное расстояние'}),
      fieldMm: h('input', {type: 'number', step: 'any', placeholder: 'мм, например 175', 'aria-label': 'Поле линзы'}), exp: h('input', {type: 'number', step: 'any', value: 1, 'aria-label': 'Расширитель пучка'}),
      note: h('input', {placeholder: 'необязательно', 'aria-label': 'Заметка'})};
    return h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, field('Название', f.name), field('Фокусное расстояние, мм', f.focal, 'выгравировано на оправе: F=…'),
      field('Поле линзы, мм', f.fieldMm, 'сторона квадрата, например 110, 150, 175'), field('Расширитель пучка', f.exp, '1, если расширителя нет; ×2 уменьшает пятно вдвое'), field('Заметка', f.note)),
    btn('Добавить и установить', async () => {
      try {
        const lens = await post('/lenses', {name: val(f.name), focal_length_mm: num(f.focal), field_mm: num(f.fieldMm), expansion: num(f.exp) ?? 1, note: val(f.note) || null});
        await put(`/devices/${d.id}/lens`, {lens_id: lens.id}); toast('Линза добавлена и установлена', 'ok'); refresh(d.id);
      } catch (e) { fail(e); }
    }, 'primary'));
  }

  async function card(d, refresh) {
    const all = await get('/lenses');
    return h('div', {class: 'stack'}, h('div', {class: 'card stack'}, h('h3', {}, 'Линза на этом лазере'),
      h('p', {class: 'muted small'}, 'Линза задаёт размер пятна на металле и рабочее поле. Сменили линзу: поставьте новую здесь, и новые платы запомнят её. Старые платы сохранят прежнюю.'), summary(d)),
    h('div', {class: 'card stack'}, h('h3', {}, 'Мои линзы'),
      table(['Линза', 'Фокус', 'Поле', 'Расширитель', 'Статус', ''], all.map((l) => lensRow(d, l, refresh)), 'Линз пока нет: добавьте первую ниже', true)),
    h('div', {class: 'card stack'}, h('h3', {}, 'Новая линза'), form(d, refresh)));
  }
  return {card};
})();
