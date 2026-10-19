/* Настройки контроллера (EZCAD): таблица по разделам, значения правятся прямо в строках; можно подтвердить, исправить,
   убрать и добавить настройку. Каждая правка сохраняется сразу (без кнопки): запросы уходят по одному,
   последний пишет полное состояние таблицы (DEC-039). Измерений правки не касаются.
   Строки и форма добавления — controller-rows.js. */
'use strict';
const DeviceController = (() => {
  const {h, patch, toast, fail, table} = App;
  const {TAB} = GlossaryController;
  const {UNREAD, working, row, addForm, small} = ControllerRows;

  function controllerCard(d, reload, wanted) {
    const c = working(d.passport.controller), photo = d.documents.find((x) => x.kind === 'controller_config');
    let section = TAB[wanted] ? wanted : c.tabs[0].key, state = 'idle', failure = '', chain = Promise.resolve();
    const keep = () => history.replaceState(null, '', `#/devices/${d.id}?tab=controller&section=${section}`);
    const status = h('span', {class: 'small', role: 'status'});
    const show = () => {
      status.className = 'small ' + (state === 'error' ? 'bad' : 'muted');
      status.textContent = {idle: 'Правки сохраняются сразу', saving: 'Сохраняю…', saved: '✓ Сохранено', error: 'Не сохранено: ' + failure}[state];
    };
    // Запросы выстраиваются в очередь: поздняя правка не обгонит раннюю, а каждый запрос несёт текущее состояние всей таблицы.
    const persist = () => {
      state = 'saving'; show();
      chain = chain.then(async () => {
        try { await patch('/devices/' + d.id, {passport: {...d.passport, controller: c}}); state = 'saved'; failure = ''; }
        catch (e) { state = 'error'; failure = e.message; fail(e); }
        show();
      });
    };
    const ctx = {help: false, change: () => { draw(); persist(); }};
    const root = h('div', {class: 'card stack'});
    window.onbeforeunload = () => (state === 'saving' || state === 'error' ? 'Не все правки сохранены' : null);

    function draw() {
      const all = c.tabs.flatMap((t) => t.fields), unread = all.filter((f) => f.value === UNREAD).length;
      const count = (s) => all.filter((f) => f.status === s && f.value !== UNREAD).length;
      const cur = c.tabs.find((t) => t.key === section);
      const tabs = h('div', {class: 'row', role: 'tablist'}, c.tabs.map((t) => h('button', {type: 'button', role: 'tab', 'aria-selected': t.key === section,
        class: 'btn btn-small' + (t.key === section ? ' primary' : ''), onClick: () => { section = t.key; keep(); draw(); }}, `${TAB[t.key]} · ${t.fields.length}`)));
      show();
      root.replaceChildren(h('h3', {}, `Настройки лазера · программа ${c.software || ''}`),
        h('p', {class: 'muted small'}, 'Настройки вашего станка из программы управления (EZCAD). Подтверждённые и напечатанные частоты (Min PWM, Max PWM) и размер поля учитываются в расчётах, остальные — справочно. '
          + 'Исправленное или добавленное вами считается подтверждённым. ✓ — значение сверено с оригиналом, × — убрать из списка. Каждая правка сохраняется сразу.'),
        h('div', {class: 'row'}, h('span', {class: 'small muted'}, `Всего ${all.length}: напечатано ${count('printed')} · от руки ${count('handwritten')} · подтверждено ${count('confirmed')} · не прочитано ${unread}`),
          h('span', {class: 'spacer'}), status, state === 'error' ? small('Повторить сохранение', 'Повторить', persist, 'Повторить') : null,
          photo ? h('a', {href: `/api/devices/${d.id}/documents/${photo.id}`, target: '_blank', rel: 'noopener'}, 'Оригинал на фото') : null,
          h('label', {class: 'row small'}, h('input', {type: 'checkbox', checked: ctx.help, onChange: (e) => { ctx.help = e.target.checked; draw(); }}), 'Пояснения')),
        tabs, table(['Настройка', 'Значение', 'Ед.', 'Надёжность', ''], cur.fields.map((f) => row(f, cur.fields, ctx)), 'В этом разделе настроек нет', true), addForm(cur.fields, ctx));
    }
    draw();
    return root;
  }
  return {controllerCard};
})();
