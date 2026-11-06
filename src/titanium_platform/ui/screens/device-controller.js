/* EZCAD controller settings are edited and saved in order, with each request writing the complete table (DEC-039). */
'use strict';
const DeviceController = (() => {
  const {h, patch, toast, fail, table} = App;
  const {TAB} = GlossaryController;
  const {isUnread, working, row, addForm, small} = ControllerRows;

  function controllerCard(d, reload, wanted) {
    const c = working(d.passport.controller), photo = d.documents.find((x) => x.kind === 'controller_config');
    let section = TAB[wanted] ? wanted : c.tabs[0].key, state = 'idle', failure = '', chain = Promise.resolve();
    const keep = () => history.replaceState(null, '', `#/devices/${d.id}?tab=controller&section=${section}`);
    const status = h('span', {class: 'small', role: 'status'});
    const show = () => {
      status.className = 'small ' + (state === 'error' ? 'bad' : 'muted');
      status.textContent = {idle: 'Changes save immediately', saving: 'Saving…', saved: '✓ Saved', error: 'Not saved: ' + failure}[state];
    };
    // Queue requests so later changes cannot overtake earlier ones; each writes the current table.
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
    window.onbeforeunload = () => (state === 'saving' || state === 'error' ? 'Some changes have not been saved' : null);

    function draw() {
      const all = c.tabs.flatMap((t) => t.fields), unread = all.filter((f) => isUnread(f.value)).length;
      const count = (s) => all.filter((f) => f.status === s && !isUnread(f.value)).length;
      const cur = c.tabs.find((t) => t.key === section);
      const tabs = h('div', {class: 'row', role: 'tablist'}, c.tabs.map((t) => h('button', {type: 'button', role: 'tab', 'aria-selected': t.key === section,
        class: 'btn btn-small' + (t.key === section ? ' primary' : ''), onClick: () => { section = t.key; keep(); draw(); }}, `${TAB[t.key]} · ${t.fields.length}`)));
      show();
      root.replaceChildren(h('h3', {}, `Laser settings · software ${c.software || ''}`),
        h('p', {class: 'muted small'}, 'Machine settings from EZCAD. Confirmed and printed frequencies (Min PWM, Max PWM) and field size are used in calculations; the rest are informational. '
          + 'Values you correct or add are considered confirmed. ✓ confirms a value against the original; × removes it. Each edit saves immediately.'),
        h('div', {class: 'row'}, h('span', {class: 'small muted'}, `Total ${all.length}: printed ${count('printed')} · handwritten ${count('handwritten')} · confirmed ${count('confirmed')} · unread ${unread}`),
          h('span', {class: 'spacer'}), status, state === 'error' ? small('Retry saving', 'Retry', persist, 'Retry') : null,
          photo ? h('a', {href: `/api/devices/${d.id}/documents/${photo.id}`, target: '_blank', rel: 'noopener'}, 'Original photograph') : null,
          h('label', {class: 'row small'}, h('input', {type: 'checkbox', checked: ctx.help, onChange: (e) => { ctx.help = e.target.checked; draw(); }}), 'Explanations')),
        tabs, table(['Setting', 'Value', 'Unit', 'Reliability', ''], cur.fields.map((f) => row(f, cur.fields, ctx)), 'No settings in this section', true), addForm(cur.fields, ctx));
    }
    draw();
    return root;
  }
  return {controllerCard};
})();
