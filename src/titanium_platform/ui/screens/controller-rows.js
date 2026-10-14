/* Строки таблицы настроек контроллера и форма добавления (DEC-039). Правка меняет рабочую копию в карточке,
   в паспорт лазера всё уходит одним сохранением (device-controller.js). Значение, введённое вами, считается подтверждённым. */
'use strict';
const ControllerRows = (() => {
  const {h, pill, fail} = App;
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
    const f = {key: h('input', {placeholder: 'название, как в EZCAD', 'aria-label': 'Название настройки'}), value: h('input', {placeholder: 'значение', 'aria-label': 'Значение'}),
      unit: h('input', {placeholder: 'ед.', 'aria-label': 'Единица', style: 'max-width:90px'})};
    const add = () => {
      const key = f.key.value.trim(), value = parse(f.value.value);
      if (!key || value === '') return fail(new Error('Укажите название и значение настройки'));
      if (fields.some((x) => x.key === key)) return fail(new Error('Такая настройка в этом разделе уже есть'));
      fields.push({key, value, unit: f.unit.value.trim() || null, status: 'confirmed'});
      ctx.change();
    };
    return h('div', {class: 'row'}, f.key, f.value, f.unit, small('Добавить настройку в этот раздел', 'Добавить настройку', add, '+ Добавить'));
  }
  return {UNREAD, STATUS, working, row, addForm, small};
})();
