/* Settings for stock, capture setups, repeatability rules and photo markers (DEC-042, DEC-063). */
'use strict';
(() => {
  const {h, get} = App;
  const TABS = [['material', 'Stock'], ['rigs', 'Capture'], ['rules', 'Repeatability'], ['markers', 'Photo markers']];

  App.register({id: 'setup', async render(ctx) {
    const tab = TABS.some((t) => t[0] === ctx.query.tab) ? ctx.query.tab : 'material';
    const reload = (t, extra) => { location.hash = `#/setup?tab=${t || tab}${extra ? '&' + extra : ''}`; App.render(); };
    const body = tab === 'material' ? await MaterialCatalog.tab(ctx)
      : tab === 'rigs' ? SetupForms.rigsTab(await get('/setups'), reload)
        : tab === 'rules' ? await SetupRules.rulesTab(ctx, reload) : await SetupRules.markersTab(reload);
    return h('div', {class: 'stack'}, h('h2', {}, 'Settings'),
      h('p', {class: 'sub'}, 'Titanium stock, capture setups, repeatability rules for each laser and lens, and coded plate markers. '
        + 'Configure lasers and lenses on the Lasers screen; set power, frequency, speed, pulse, spacing and passes for each plate and layer.'),
      h('div', {class: 'toolbar'}, h('span', {class: 'spacer'}),
        h('div', {class: 'row', role: 'tablist'}, TABS.map(([id, label]) => h('a', {href: `#/setup?tab=${id}`, class: 'btn' + (id === tab ? ' primary' : ''), role: 'tab', 'aria-selected': id === tab}, label)))),
      body);
  }});
})();
