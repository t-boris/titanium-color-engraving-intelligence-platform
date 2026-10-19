/* Формы лазера: создание из шаблона или по паспорту, правка паспорта, загрузка документа (REQ-017). */
'use strict';
const DeviceForms = (() => {
  const {h, btn, field, get, post, patch, form, toast, fail} = App;
  const val = (el) => el.value.trim();
  const num = (el) => (val(el) === '' ? null : +val(el));
  const KINDS = [['test_report', 'Протокол испытаний'], ['cutoff_table', 'Таблица частот среза'], ['waveform', 'Формы импульса'],
    ['controller_config', 'Настройки контроллера'], ['packing_list', 'Комплектность'], ['manual', 'Руководство'], ['other', 'Другое']];
  const KIND = Object.fromEntries(KINDS);

  /** «20 252» на строку; «CW» или пусто вместо частоты — режим без среза. Возвращает ступени паспорта. */
  function parseSteps(text) {
    return text.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
      const [w, c] = l.split(/[\s;:,]+/);
      const cutoff = c == null || /^(cw|нет|—|-)$/i.test(c) ? null : +c;
      return {pulse_width_ns: +w, cutoff_khz: cutoff};
    });
  }
  const stepsText = (steps) => steps.map((s) => `${s.pulse_width_ns} ${s.cutoff_khz == null ? 'CW' : s.cutoff_khz}`).join('\n');
  const area = (value, rows) => h('textarea', {rows, style: 'height:auto;min-height:44px', value});

  async function templateForm(done) {
    const templates = await get('/device-templates');
    const pick = h('select', {'aria-label': 'Шаблон лазера'}, templates.map((t) => h('option', {value: t.key}, t.name)));
    const serial = h('input', {placeholder: 'например, MC2BDJD71684'});
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'}, field('Шаблон', pick), field('Серийный номер', serial, 'в названии он покажется сам; его можно изменить позже')),
      h('p', {class: 'muted small'}, 'В шаблоне — таблица производителя: ступени длительности импульса и частота среза мощности для каждой.'),
      btn('Добавить лазер из шаблона', async () => {
        try { const d = await post('/devices/from-template', {template: pick.value, serial: val(serial) || null}); toast('Лазер добавлен', 'ok'); done(d.id); } catch (e) { fail(e); }
      }, 'primary'));
  }

  function createForm(done) {
    const f = {name: h('input'), manufacturer: h('input'), model: h('input'), serial: h('input'),
      power: h('input', {type: 'number', step: 'any', placeholder: 'Вт'}), lo: h('input', {type: 'number', step: 'any', value: 1}), hi: h('input', {type: 'number', step: 'any', placeholder: 'кГц'}),
      wl: h('input', {type: 'number', step: 'any', placeholder: 'нм'}), steps: area('1 CW\n2 1950', 6)};
    return h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, field('Название', f.name), field('Производитель', f.manufacturer), field('Модель', f.model),
      field('Серийный номер', f.serial, 'необязательно'), field('Номинальная мощность, Вт', f.power), field('Длина волны, нм', f.wl, 'необязательно'),
      field('Частота повторения от, кГц', f.lo), field('Частота повторения до, кГц', f.hi)),
    field('Ступени длительности импульса', f.steps, 'по строке на ступень: длительность, нс, и частота среза, кГц; CW — без среза'),
    btn('Создать лазер', async () => {
      const passport = {rated_power_w: num(f.power), wavelength_nm: num(f.wl), repetition_rate_khz: {min: num(f.lo), max: num(f.hi)}, pulse_steps: parseSteps(f.steps.value)};
      try { const d = await post('/devices', {name: val(f.name), manufacturer: val(f.manufacturer), model: val(f.model), serial: val(f.serial), passport}); toast('Лазер создан', 'ok'); done(d.id); } catch (e) { fail(e); }
    }, 'primary'));
  }

  /** Правка того, что можно уточнять позже: серийный номер, описание, M², ступени, открытые вопросы. Измерения не затрагиваются.
      Измеренный диаметр пятна — свойство линзы, а не лазера: он вводится на вкладке «Линза» и хранится у линзы (REQ-019). */
  function editForm(d, done) {
    const p = d.passport;
    const f = {serial: h('input', {value: d.serial || ''}),
      m2: h('input', {type: 'number', step: 'any', value: p.m2 ?? '', placeholder: 'например, 1.3'}), m2max: h('input', {type: 'number', step: 'any', value: p.m2_max ?? '', placeholder: '1.5'}),
      beam: h('input', {type: 'number', step: 'any', value: p.beam_diameter_mm ?? '', placeholder: 'мм'}),
      desc: area(d.description || '', 4), open: area((p.open_items || []).join('\n'), 3), steps: area(stepsText(p.pulse_steps), 8)};
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'}, field('Серийный номер', f.serial),
      h('p', {class: 'muted small'}, 'Измеренный диаметр пятна вводится на вкладке «Линза»: он принадлежит линзе, с которой его мерили, и при замене линзы не переносится.')),
    h('div', {class: 'grid g3'}, field('M² вашего лазера', f.m2, 'качество пучка; без него пятно известно только в границах'), field('M² не больше (из руководства)', f.m2max, 'для вашей модели — 1.5'),
      field('Диаметр пучка на линзе, мм', f.beam, 'на выходе лазера 7 мм; умножьте на расширитель, если он есть')),
      field('Описание', f.desc), field('Ваши заметки к паспорту', f.open, 'по строке; вопросы по непрочитанным и неподтверждённым значениям, диаметру пятна и номеру считает приложение само'),
      field('Ступени длительности импульса', f.steps),
      btn('Сохранить паспорт', async () => {
        const passport = {...p, m2: num(f.m2), m2_max: num(f.m2max), beam_diameter_mm: num(f.beam), open_items: f.open.value.split('\n').map((x) => x.trim()).filter(Boolean), pulse_steps: parseSteps(f.steps.value)};
        try { await patch('/devices/' + d.id, {serial: val(f.serial) || null, description: val(f.desc) || null, passport}); toast('Паспорт сохранён', 'ok'); done(d.id); } catch (e) { fail(e); }
      }, 'primary'));
  }

  function uploadForm(d, done) {
    const kind = h('select', {'aria-label': 'Вид документа'}, KINDS.map(([k, l]) => h('option', {value: k}, l)));
    const title = h('input', {placeholder: 'по умолчанию — имя файла'});
    const file = h('input', {type: 'file', accept: 'image/jpeg,image/png,application/pdf,text/plain', 'aria-label': 'Документ'});
    return h('div', {class: 'grid g3'}, field('Вид документа', kind), field('Название', title), field('Файл', App.filePick(file, 'Выбрать документ')),
      btn('Добавить документ', async () => {
        const fd = new FormData();
        fd.append('kind', kind.value); fd.append('title', val(title));
        if (file.files[0]) fd.append('file', file.files[0]);
        try { await form(`/devices/${d.id}/documents`, fd); toast('Документ добавлен', 'ok'); done(d.id); } catch (e) { fail(e); }
      }, 'primary'));
  }
  return {templateForm, createForm, editForm, uploadForm, KIND};
})();
