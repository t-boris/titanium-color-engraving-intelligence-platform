/* Вкладка «Линза»: какая линза стоит на лазере, какое пятно и поле она даёт, список линз, замена и новая линза (REQ-019, DEC-041).
   Пятно и поле считает сервер (characterization); здесь только слова и формы. Замена линзы сохраняется сразу.
   M² и измеренное пятно вводятся на этой же вкладке: сообщение о том, чего не хватает, всегда рядом с полем для ответа.
   Измеренное пятно хранится у линзы, с которой его мерили (REQ-019); M² — у лазера. */
'use strict';
const DeviceLens = (() => {
  const {h, btn, field, pill, get, post, put, patch, del, toast, fail, confirmBox, modal, table, facts} = App;
  const val = (el) => el.value.trim();
  const num = (el) => (val(el) === '' ? null : +val(el).replace(',', '.'));
  const g = (v, d = 4) => (v == null ? '—' : String(+(+v).toPrecision(d)));
  const SOURCE = {lens: 'по линзе', 'lens and laser settings': 'меньшее из линзы и настроек лазера', 'Field Size': 'по настройкам: Field Size', 'Size Width / Size Height': 'по настройкам: размер рабочей области'};

  /** M² и измеренное пятно вводятся здесь же, где о них говорится: искать их на другой вкладке не нужно. M² — свойство пучка
      лазера и хранится в паспорте; измеренное пятно — свойство линзы, с которой его мерили, и хранится в записи линзы:
      при замене линзы оно к другой линзе не переходит (REQ-019). Сохраняется только то, что вы изменили. */
  function spotForm(d, refresh) {
    const p = d.passport, lens = d.lens;
    const f = {m2: h('input', {type: 'number', step: 'any', min: 0, value: p.m2 ?? '', placeholder: 'например, 1.3', 'aria-label': 'M² вашего лазера'}),
      spot: h('input', {type: 'number', step: 'any', min: 0, value: lens.spot_diameter_um ?? '', placeholder: 'мкм', 'aria-label': `Диаметр пятна, измеренный с линзой «${lens.name}», мкм`})};
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'},
      field('M² вашего лазера', f.m2, 'качество пучка: из протокола испытаний или от производителя; без него пятно известно только в границах'),
      field(`Или диаметр пятна, измеренный с линзой «${lens.name}», мкм`, f.spot, 'если измеряли: имеет приоритет над расчётом и хранится у этой линзы, при замене линзы не переносится')),
    btn('Сохранить', async () => {
      try {
        if (num(f.m2) !== (p.m2 ?? null)) await patch('/devices/' + d.id, {passport: {...p, m2: num(f.m2)}});
        if (num(f.spot) !== (lens.spot_diameter_um ?? null)) await patch('/lenses/' + lens.id, {spot_diameter_um: num(f.spot)});
        toast('Сохранено', 'ok'); refresh(d.id);
      } catch (e) { fail(e); }
    }, 'primary'));
  }

  function summary(d, refresh) {
    const c = d.characterization, spot = c.items.find((i) => i.key === 'spot_diameter'), lens = d.lens;
    if (!lens) {
      return h('div', {class: 'alert warn'}, 'Линза не установлена: пятно и рабочее поле от неё не рассчитываются. Выберите линзу ниже или создайте новую.');
    }
    const range = spot.low ? `${g(spot.low, 3)}${spot.high ? '–' + g(spot.high, 3) : '+'} мкм (границы, в расчётах не участвуют)` : null;
    const wf = c.work_field_mm;
    return h('div', {class: 'stack'}, facts([['Установлена', App.lensLabel(lens) + (lens.expansion !== 1 ? ` · расширитель ×${lens.expansion}` : '')],
      ['Диаметр пятна', spot.value != null ? `${g(spot.value, 3)} мкм (${spot.basis === 'measured' ? 'измерено вами' : 'рассчитано'})` : (range || 'не определён')],
      ['Рабочее поле', wf ? `${g(wf.width)} × ${g(wf.height)} мм (${SOURCE[wf.source] || wf.source})` : 'не определено']]),
    spot.waiting_for.includes('m2') ? h('div', {class: 'alert warn'}, `Линза учтена: фокус ${g(lens.focal_length_mm)} мм, диаметр пучка на ней ${g(d.passport.beam_diameter_mm)} мм. Для диаметра пятна не хватает только M² (качества пучка).`
      + (d.passport.m2_max ? ` В руководстве сказано «не больше ${g(d.passport.m2_max)}»: это предел, а не число вашего лазера, поэтому в расчётах его нет.` : '') + ' Впишите M² или измеренное пятно ниже.') : null,
    spot.waiting_for.includes('focal_length') ? h('div', {class: 'alert warn'}, 'Фокусное расстояние этой линзы не указано: диаметр пятна, плотность энергии и перекрытие импульсов не рассчитываются. '
      + 'Остальные расчёты рабочей точки доступны. Укажите фокус в списке линз ниже или впишите измеренное пятно.') : null,
    spotForm(d, refresh),                                    // всегда на виду: введённое значение можно поправить здесь же
    wf && wf.settings_exceeds_lens ? h('div', {class: 'alert warn'}, 'Поле в настройках лазера больше поля линзы: плата ограничена полем линзы.') : null);
  }

  /** Строка линзы: поставить, править, удалить. */
  function lensRow(d, l, refresh) {
    const here = d.lens && d.lens.id === l.id, elsewhere = l.installed_on && !here;
    const set = btn(here ? 'Снять' : 'Поставить', async () => {
      try { await put(`/devices/${d.id}/lens`, {lens_id: here ? null : l.id}); toast(here ? 'Линза снята' : 'Линза установлена', 'ok'); refresh(d.id); } catch (e) { fail(e); }
    }, here ? '' : 'primary', !!elsewhere);
    const remove = btn('Удалить', () => confirmBox('Удалить линзу', `«${l.name}». Установленную линзу и линзу, с которой есть платы или измерения, удалить нельзя.`, 'Удалить',
      async () => { await del('/lenses/' + l.id); toast('Линза удалена', 'ok'); refresh(d.id); }), 'danger', here);
    const focal = l.focal_length_mm == null ? btn('Указать фокус', () => focalDialog(d, l, refresh), 'btn-small') : `${g(l.focal_length_mm)} мм`;
    return [h('div', {}, h('strong', {}, l.name), l.note ? h('div', {class: 'small muted'}, l.note) : null), focal, l.field_mm ? `${g(l.field_mm)} мм` : '—',
      l.expansion === 1 ? '—' : '×' + l.expansion, l.spot_diameter_um != null ? `${g(l.spot_diameter_um, 3)} мкм` : 'не измерено',
      here ? pill('установлена', 'ok') : elsewhere ? pill('на «' + l.installed_on.name + '»', 'warn') : '', h('span', {class: 'row'}, set, remove)];
  }

  /** Фокусное расстояние линзы, записанной без него: запись дополняется, данные с этой линзой остаются её данными (DEC-063). */
  function focalDialog(d, l, refresh) {
    const focal = h('input', {type: 'number', step: 'any', placeholder: 'мм', 'aria-label': 'Фокусное расстояние'});
    modal('Фокусное расстояние линзы', h('div', {class: 'stack'}, h('p', {}, `«${l.name}»: впишите значение с оправы или из документации.`), field('Фокусное расстояние, мм', focal)), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Сохранить', cls: 'primary', run: async (m) => { await patch('/lenses/' + l.id, {focal_length_mm: num(focal)}); m.close(); toast('Фокус сохранён', 'ok'); refresh(d.id); }}]);
  }

  function form(d, refresh) {
    const f = {name: h('input', {placeholder: 'например, F-theta 254', 'aria-label': 'Название линзы'}), focal: h('input', {type: 'number', step: 'any', placeholder: 'мм', 'aria-label': 'Фокусное расстояние'}),
      fieldMm: h('input', {type: 'number', step: 'any', placeholder: 'мм, например 175', 'aria-label': 'Поле линзы'}), exp: h('input', {type: 'number', step: 'any', value: 1, 'aria-label': 'Расширитель пучка'}),
      note: h('input', {placeholder: 'необязательно', 'aria-label': 'Заметка'})};
    return h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, field('Название', f.name), field('Фокусное расстояние, мм', f.focal, 'выгравировано на оправе: F=…; если неизвестно, оставьте пустым'),
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
      h('p', {class: 'muted small'}, 'Линза задаёт размер пятна на металле и рабочее поле. Сменили линзу: поставьте новую здесь, и новые платы запомнят её. Старые платы сохранят прежнюю.'), summary(d, refresh)),
    h('div', {class: 'card stack'}, h('h3', {}, 'Мои линзы'),
      table(['Линза', 'Фокус', 'Поле', 'Расширитель', 'Измеренное пятно', 'Статус', ''], all.map((l) => lensRow(d, l, refresh)), 'Линз пока нет: добавьте первую ниже', true)),
    h('div', {class: 'card stack'}, h('h3', {}, 'Новая линза'), form(d, refresh)));
  }
  return {card};
})();
