/* Формы лазера: создание из шаблона или по паспорту, правка паспорта, загрузка документа (REQ-017). */
'use strict';
const DeviceForms = (() => {
  const {h, btn, get, post, patch, form, toast} = App;
  const KINDS = [['test_report', 'Протокол испытаний'], ['cutoff_table', 'Таблица частот среза'], ['waveform', 'Формы импульса'],
    ['controller_config', 'Настройки контроллера'], ['packing_list', 'Комплектность'], ['manual', 'Руководство'], ['other', 'Другое']];
  const KIND = Object.fromEntries(KINDS);

  /** «20 252» на строку; «CW» или пусто вместо частоты — режим без среза. Возвращает ступени паспорта. Строка, которую нельзя прочитать,
      не пропускается и не исправляется: форма называет её номер и причину (ux-save-feedback-p0, REQ-003). */
  function readSteps(area) {
    return () => {
      const steps = [];
      const lines = area.value.split('\n');
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].trim();
        if (!line) continue;
        const [w, c] = line.split(/[\s;:,]+/);
        const width = Forms.parse(w, Forms.QUANTITIES.pulseWidth, {required: true});
        if (!width.ok) return {ok: false, message: `Строка ${i + 1}: длительность импульса. ${width.message}`};
        let cutoff = null;
        if (c != null && !/^(cw|нет|—|-)$/i.test(c)) {
          const parsed = Forms.parse(c, Forms.QUANTITIES.cutoff, {required: true});
          if (!parsed.ok) return {ok: false, message: `Строка ${i + 1}: частота среза. ${parsed.message}`};
          cutoff = parsed.value;
        }
        steps.push({pulse_width_ns: width.value, cutoff_khz: cutoff});
      }
      return steps.length ? {ok: true, value: steps} : {ok: false, message: 'Нужна хотя бы одна ступень: длительность, нс, и частота среза, кГц (или CW)'};
    };
  }
  const stepsText = (steps) => steps.map((s) => `${s.pulse_width_ns} ${s.cutoff_khz == null ? 'CW' : s.cutoff_khz}`).join('\n');
  const area = (value, rows) => h('textarea', {rows, style: 'height:auto;min-height:44px', value});

  async function templateForm(done) {
    const templates = await get('/device-templates');
    const f = Forms.create();
    const pick = h('select', {}, templates.map((t) => h('option', {value: t.key}, t.name)));
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'}, f.add('template', 'Шаблон', pick, {required: true}),
      f.add('serial', 'Серийный номер', h('input', {placeholder: 'например, MC2BDJD71684'}), {help: 'в названии он покажется сам; его можно изменить позже'})),
      h('p', {class: 'muted small'}, 'В шаблоне — таблица производителя: ступени длительности импульса и частота среза мощности для каждой.'), f.error,
      btn('Добавить лазер из шаблона', async () => {
        const v = f.collect();
        if (!v) return;
        try { const d = await post('/devices/from-template', {template: v.template, serial: v.serial}); toast('Лазер добавлен', 'ok'); done(d.id); } catch (e) { f.fail(e); }
      }, 'primary'));
  }

  function createForm(done) {
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const number = (q, attrs) => Forms.numberInput(q, attrs);
    const steps = area('1 CW\n2 1950', 6);
    return h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, f.add('name', 'Название', h('input'), {required: true}),
      f.add('manufacturer', 'Производитель', h('input'), {empty: ''}), f.add('model', 'Модель', h('input'), {empty: ''}),
      f.add('serial', 'Серийный номер', h('input'), {help: 'необязательно', empty: ''}),
      f.add('power', 'Номинальная мощность', number(Q.ratedPower), {quantity: 'ratedPower', required: true}),
      f.add('wavelength', 'Длина волны', number(Q.wavelength), {quantity: 'wavelength', help: 'необязательно'}),
      f.add('lo', 'Частота повторения от', number(Q.repetitionRate, {value: 1}), {quantity: 'repetitionRate', required: true}),
      f.add('hi', 'Частота повторения до', number(Q.repetitionRate), {quantity: 'repetitionRate', required: true, help: 'выше, чем «от»'})),
    f.add('steps', 'Ступени длительности импульса', steps, {required: true, read: readSteps(steps), help: 'по строке на ступень: длительность, нс, и частота среза, кГц; CW — без среза'}),
    f.error,
    btn('Создать лазер', async () => {
      const v = f.collect();
      if (!v) return;
      const passport = {rated_power_w: v.power, wavelength_nm: v.wavelength, repetition_rate_khz: {min: v.lo, max: v.hi}, pulse_steps: v.steps};
      try { const d = await post('/devices', {name: v.name, manufacturer: v.manufacturer, model: v.model, serial: v.serial, passport}); toast('Лазер создан', 'ok'); done(d.id); } catch (e) { f.fail(e); }
    }, 'primary'));
  }

  /** Правка того, что можно уточнять позже: серийный номер, описание, M², ступени, открытые вопросы. Измерения не затрагиваются.
      Измеренный диаметр пятна — свойство линзы, а не лазера: он вводится на вкладке «Линза» и хранится у линзы (REQ-019). */
  function editForm(d, done) {
    const p = d.passport;
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const number = (q, attrs) => Forms.numberInput(q, attrs);
    const steps = area(stepsText(p.pulse_steps), 8);
    const open = area((p.open_items || []).join('\n'), 3);
    return h('div', {class: 'stack'}, h('div', {class: 'grid g2'}, f.add('serial', 'Серийный номер', h('input', {value: d.serial || ''})),
      h('p', {class: 'muted small'}, 'Измеренный диаметр пятна вводится на вкладке «Линза»: он принадлежит линзе, с которой его мерили, и при замене линзы не переносится.')),
    h('div', {class: 'grid g3'}, f.add('m2', 'M² вашего лазера', number(Q.m2, {value: p.m2 ?? '', placeholder: 'например, 1.3'}), {quantity: 'm2', help: 'качество пучка; без него пятно известно только в границах'}),
      f.add('m2max', 'M² не больше (из руководства)', number(Q.m2, {value: p.m2_max ?? '', placeholder: '1.5'}), {quantity: 'm2', help: 'для вашей модели — 1.5'}),
      f.add('beam', 'Диаметр пучка на линзе', number(Q.beamDiameter, {value: p.beam_diameter_mm ?? ''}), {quantity: 'beamDiameter', help: 'на выходе лазера 7 мм; умножьте на расширитель, если он есть'})),
      f.add('defw', 'Q-Pulse по умолчанию', number(Forms.QUANTITIES.pulseWidth, {value: p.default_pulse_width_ns ?? '', placeholder: 'например 200'}),
        {quantity: 'pulseWidth', help: 'LightBurn не записывает Q-Pulse в слой, если он равен этому значению; такой слой получает его. Должно лежать между самой короткой и самой длинной ступенью'}),
      f.add('desc', 'Описание', area(d.description || '', 4)),
      f.add('open', 'Ваши заметки к паспорту', open, {read: () => ({ok: true, value: open.value.split('\n').map((x) => x.trim()).filter(Boolean)}),
        help: 'по строке; вопросы по непрочитанным и неподтверждённым значениям, диаметру пятна и номеру считает приложение само'}),
      f.add('steps', 'Ступени длительности импульса', steps, {required: true, read: readSteps(steps)}),
      f.error,
      btn('Сохранить паспорт', async () => {
        const v = f.collect();
        if (!v) return;
        const passport = {...p, m2: v.m2, m2_max: v.m2max, beam_diameter_mm: v.beam, default_pulse_width_ns: v.defw, open_items: v.open, pulse_steps: v.steps};
        try { await patch('/devices/' + d.id, {serial: v.serial, description: v.desc, passport}); toast('Паспорт сохранён', 'ok'); done(d.id); } catch (e) { f.fail(e); }
      }, 'primary'));
  }

  function uploadForm(d, done) {
    const f = Forms.create();
    const kind = h('select', {}, KINDS.map(([k, l]) => h('option', {value: k}, l)));
    const file = h('input', {type: 'file', accept: 'image/jpeg,image/png,application/pdf,text/plain'});
    return h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, f.add('kind', 'Вид документа', kind, {required: true}),
      f.add('title', 'Название', h('input', {placeholder: 'по умолчанию — имя файла'}), {empty: ''}),
      f.add('file', 'Файл', App.filePick(file, 'Выбрать документ'), {required: true,
        read: () => (file.files[0] ? {ok: true, value: file.files[0]} : {ok: false, message: 'Выберите файл документа: изображение, PDF или текст'})})), f.error,
      btn('Добавить документ', async () => {
        const v = f.collect();
        if (!v) return;
        const fd = new FormData();
        fd.append('kind', v.kind); fd.append('title', v.title);
        fd.append('file', v.file);
        try { await form(`/devices/${d.id}/documents`, fd); toast('Документ добавлен', 'ok'); done(d.id); } catch (e) { f.fail(e); }
      }, 'primary'));
  }
  return {templateForm, createForm, editForm, uploadForm, KIND, KINDS};
})();
