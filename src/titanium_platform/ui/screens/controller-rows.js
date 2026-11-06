/* Controller setting rows edit a working copy saved by device-controller.js (DEC-039). Entered values are confirmed. */
'use strict';
const ControllerRows = (() => {
  const {h, pill} = App;
  const {TAB, HELP} = GlossaryController;
  // Preserve the legacy stored sentinel while displaying an English placeholder.
  const UNREAD = 'see photo';
  const isUnread = (value) => value === UNREAD || value === '\u0441\u043c. \u0444\u043e\u0442\u043e';
  const STATUS = {printed: ['printed', 'ok'], handwritten: ['handwritten', 'warn'], confirmed: ['confirmed', 'ok']};
  const parse = (text) => (/^-?\d+([.,]\d+)?$/.test(text.trim()) ? +text.trim().replace(',', '.') : text.trim());
  const small = (title, label, onClick, text) => h('button', {type: 'button', class: 'btn btn-small', title, 'aria-label': label, onClick}, text);

  /** Copy the controller with all five tabs in their usual order, including empty tabs. */
  function working(controller) {
    const c = JSON.parse(JSON.stringify(controller || {software: 'EZCAD', source: null, tabs: []}));
    c.tabs = Object.keys(TAB).map((key) => c.tabs.find((t) => t.key === key) || {key, fields: []});
    return c;
  }

  /** Use a yes/no selector for booleans and a text input otherwise; empty input is not accepted. */
  function valueInput(f, ctx) {
    if (typeof f.value === 'boolean') {
      return h('select', {'aria-label': f.key, onChange: (e) => { f.value = e.target.value === 'yes'; f.status = 'confirmed'; ctx.change(); }},
        ['yes', 'no'].map((v) => h('option', {value: v, selected: (v === 'yes') === f.value}, v)));
    }
    return h('input', {value: isUnread(f.value) ? '' : f.value, placeholder: 'Not read from photo', 'aria-label': f.key, style: 'min-width:90px', onChange: (e) => {
      const v = parse(e.target.value);
      if (v === '' || v === f.value) { e.target.value = isUnread(f.value) ? '' : f.value; return; }
      f.value = v; f.status = isUnread(v) ? 'handwritten' : 'confirmed'; ctx.change();
    }});
  }

  /** ctx: {help: show explanations, change: redraw the card}. */
  function row(f, fields, ctx) {
    const unread = isUnread(f.value);
    const confirm = f.status !== 'confirmed' && !unread
      ? small('Confirm: value checked against the original', 'Confirm ' + f.key, () => { f.status = 'confirmed'; ctx.change(); }, '✓') : null;
    const remove = small('Remove setting from the list', 'Remove ' + f.key, () => { fields.splice(fields.indexOf(f), 1); ctx.change(); }, '×');
    return [h('div', {title: HELP[f.key] || ''}, h('strong', {}, f.key), ctx.help && HELP[f.key] ? h('div', {class: 'small muted'}, HELP[f.key]) : null),
      valueInput(f, ctx), f.unit || '', unread ? pill('not read', 'bad') : pill(...STATUS[f.status]), h('span', {class: 'row'}, confirm, remove)];
  }

  function addForm(fields, ctx) {
    const f = {key: h('input', {placeholder: 'name as in EZCAD'}), value: h('input', {placeholder: 'value'}),
      unit: h('input', {placeholder: 'unit', style: 'max-width:90px'})};
    // what is wrong is said beside the box it is about, and what was typed stays; the unit is free text and may stay empty
    const form = Forms.create();
    const boxes = [
      form.add('key', 'Setting name', f.key, {required: true, read: () => {
        const key = f.key.value.trim();
        if (!key) return {ok: false, message: 'Enter a setting name'};
        return fields.some((x) => x.key === key) ? {ok: false, message: 'This setting already exists in this section'} : {ok: true, value: key};
      }}),
      form.add('value', 'Value', f.value, {required: true, read: () => {
        const value = parse(f.value.value);
        return value === '' ? {ok: false, message: 'Enter a setting value'} : {ok: true, value};
      }}),
      form.add('unit', 'Unit', f.unit, {read: () => ({ok: true, value: f.unit.value.trim() || null})})];
    const add = () => {
      const v = form.collect();
      if (!v) return;
      fields.push({key: v.key, value: v.value, unit: v.unit, status: 'confirmed'});
      ctx.change();
    };
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, ...boxes, small('Add a setting to this section', 'Add setting', add, '+ Add')), form.error);
  }
  return {UNREAD, isUnread, STATUS, working, row, addForm, small};
})();
