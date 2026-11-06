/* Строки таблицы настроек контроллера и форма добавления (DEC-039). Правка меняет рабочую копию в карточке,
   в паспорт лазера всё уходит одним сохранением (device-controller.js). Значение, введённое вами, считается подтверждённым. */
'use strict';
const ControllerRows = (() => {
  const {h, pill} = App;
  const {TAB, HELP} = GlossaryController;
  const UNREAD = 'см. фото';
  const STATUS = {printed: ['напечатано', 'ok'], handwritten: ['от руки', 'warn'], confirmed: ['подтверждено', 'ok']};
  const parse = (text) => (/^-?\d+([.,]\d+)?$/.test(text.trim()) ? +text.trim().replace(',', '.') : text.trim());
  const small = (title, label, onClick, text) => h('button', {type: 'button', class: 'btn btn-small', title, 'aria-label': label, onClick}, text);

  /** Копия раздела контроллера со всеми пятью вкладками в привычном порядке, даже если лазер их ещё не заполнял. */
  function working(controller) {
    const c = JSON.parse(JSON.stringify(controller || {software: 'EZCAD', source: null, tabs: []}));
    c.tabs = Object.keys(TAB).map((key) => c.tabs.find((t) => t.key === key) || {key, fields: []});
    return c;
  }

  /** Поле значения: список «да/нет» для флажков, иначе текстовое поле; пустой ввод не принимается. */
  function valueInput(f, ctx) {
    if (typeof f.value === 'boolean') {
      return h('select', {'aria-label': f.key, onChange: (e) => { f.value = e.target.value === 'да'; f.status = 'confirmed'; ctx.change(); }},
        ['да', 'нет'].map((v) => h('option', {value: v, selected: (v === 'да') === f.value}, v)));
    }
    return h('input', {value: f.value, placeholder: UNREAD, 'aria-label': f.key, style: 'min-width:90px', onChange: (e) => {
      const v = parse(e.target.value);
      if (v === '' || v === f.value) { e.target.value = f.value; return; }
      f.value = v; f.status = v === UNREAD ? 'handwritten' : 'confirmed'; ctx.change();
    }});
  }

  /** ctx: {help: показывать ли пояснения, change: перерисовать карточку}. */
  function row(f, fields, ctx) {
    const unread = f.value === UNREAD;
    const confirm = f.status !== 'confirmed' && !unread
      ? small('Подтвердить: значение сверено с оригиналом', 'Подтвердить ' + f.key, () => { f.status = 'confirmed'; ctx.change(); }, '✓') : null;
    const remove = small('Убрать настройку из списка', 'Убрать ' + f.key, () => { fields.splice(fields.indexOf(f), 1); ctx.change(); }, '×');
    return [h('div', {title: HELP[f.key] || ''}, h('strong', {}, f.key), ctx.help && HELP[f.key] ? h('div', {class: 'small muted'}, HELP[f.key]) : null),
      valueInput(f, ctx), f.unit || '', unread ? pill('не прочитано', 'bad') : pill(...STATUS[f.status]), h('span', {class: 'row'}, confirm, remove)];
  }

  function addForm(fields, ctx) {
    const f = {key: h('input', {placeholder: 'название, как в EZCAD'}), value: h('input', {placeholder: 'значение'}),
      unit: h('input', {placeholder: 'ед.', style: 'max-width:90px'})};
    // what is wrong is said beside the box it is about, and what was typed stays; the unit is free text and may stay empty
    const form = Forms.create();
    const boxes = [
      form.add('key', 'Название настройки', f.key, {required: true, read: () => {
        const key = f.key.value.trim();
        if (!key) return {ok: false, message: 'Укажите название настройки'};
        return fields.some((x) => x.key === key) ? {ok: false, message: 'Такая настройка в этом разделе уже есть'} : {ok: true, value: key};
      }}),
      form.add('value', 'Значение', f.value, {required: true, read: () => {
        const value = parse(f.value.value);
        return value === '' ? {ok: false, message: 'Укажите значение настройки'} : {ok: true, value};
      }}),
      form.add('unit', 'Единица', f.unit, {read: () => ({ok: true, value: f.unit.value.trim() || null})})];
    const add = () => {
      const v = form.collect();
      if (!v) return;
      fields.push({key: v.key, value: v.value, unit: v.unit, status: 'confirmed'});
      ctx.change();
    };
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, ...boxes, small('Добавить настройку в этот раздел', 'Добавить настройку', add, '+ Добавить')), form.error);
  }
  return {UNREAD, STATUS, working, row, addForm, small};
})();
