/* Настройки контроллера (EZCAD): таблица по разделам, значения правятся прямо в строках; можно подтвердить, исправить,
   убрать и добавить настройку. Правки копятся в карточке и уходят одним сохранением в паспорт лазера (DEC-039);
   измерений они не касаются. Строки и форма добавления — controller-rows.js. */
'use strict';
const DeviceController = (() => {
  const {h, patch, toast, fail, table} = App;
  const {TAB} = GlossaryController;
  const {UNREAD, working, row, addForm, small} = ControllerRows;

  function controllerCard(d, reload, wanted) {
    const c = working(d.passport.controller), photo = d.documents.find((x) => x.kind === 'controller_config');
    let section = TAB[wanted] ? wanted : c.tabs[0].key, dirty = false;
    const ctx = {help: false, change: () => { dirty = true; draw(); }};
    const root = h('div', {class: 'card stack'});
    const save = async () => {
      try { await patch('/devices/' + d.id, {passport: {...d.passport, controller: c}}); toast('Настройки сохранены', 'ok'); reload(d.id); } catch (e) { fail(e); }
    };

    function draw() {
      const all = c.tabs.flatMap((t) => t.fields), unread = all.filter((f) => f.value === UNREAD).length;
      const count = (s) => all.filter((f) => f.status === s && f.value !== UNREAD).length;
      const cur = c.tabs.find((t) => t.key === section);
      const tabs = h('div', {class: 'row', role: 'tablist'}, c.tabs.map((t) => h('button', {type: 'button', role: 'tab', 'aria-selected': t.key === section,
        class: 'btn btn-small' + (t.key === section ? ' primary' : ''), onClick: () => { section = t.key; draw(); }}, `${TAB[t.key]} · ${t.fields.length}`)));
      root.replaceChildren(h('h3', {}, `Настройки контроллера ${c.software || ''}`),
        h('p', {class: 'muted small'}, 'Настройки программы управления лазером (EZCAD). В расчётах приложения они не участвуют, нужны, чтобы настроить станок так же. '
          + 'Исправленное или добавленное вами считается подтверждённым. ✓ — значение сверено с оригиналом, × — убрать из списка.'),
        h('div', {class: 'row'}, h('span', {class: 'small muted'}, `Всего ${all.length}: напечатано ${count('printed')} · от руки ${count('handwritten')} · подтверждено ${count('confirmed')} · не прочитано ${unread}`),
          h('span', {class: 'spacer'}), photo ? h('a', {href: `/api/devices/${d.id}/documents/${photo.id}`, target: '_blank', rel: 'noopener'}, 'Оригинал на фото') : null,
          h('label', {class: 'row small'}, h('input', {type: 'checkbox', checked: ctx.help, onChange: (e) => { ctx.help = e.target.checked; draw(); }}), 'Пояснения')),
        tabs, table(['Настройка', 'Значение', 'Ед.', 'Надёжность', ''], cur.fields.map((f) => row(f, cur.fields, ctx)), 'В этом разделе настроек нет', true), addForm(cur.fields, ctx),
        dirty ? h('div', {class: 'alert warn row'}, 'Есть несохранённые изменения.', h('span', {class: 'spacer'}),
          small('Записать в паспорт лазера', 'Сохранить', save, 'Сохранить'), small('Отменить все правки', 'Отменить', () => reload(d.id), 'Отменить')) : null);
    }
    draw();
    return root;
  }
  return {controllerCard};
})();
