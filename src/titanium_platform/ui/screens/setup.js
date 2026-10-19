/* Настройки: заготовки титана, установки съёмки, правила оценки повторов для лазера с линзой и слой кодовых меток.
   Лазеры и линзы — на экране «Лазеры»; рабочие параметры задаются для каждой платы и слоя (DEC-042, DEC-063). */
'use strict';
(() => {
  const {h, get} = App;
  const TABS = [['material', 'Титан'], ['rigs', 'Съёмка'], ['rules', 'Оценка повторов'], ['markers', 'Метки для фото']];

  App.register({id: 'setup', async render(ctx) {
    const tab = TABS.some((t) => t[0] === ctx.query.tab) ? ctx.query.tab : 'material';
    const reload = (t, extra) => { location.hash = `#/setup?tab=${t || tab}${extra ? '&' + extra : ''}`; App.render(); };
    const body = tab === 'material' ? SetupForms.materialTab(await get('/materials'), reload)
      : tab === 'rigs' ? SetupForms.rigsTab(await get('/setups'), reload)
        : tab === 'rules' ? await SetupRules.rulesTab(ctx, reload) : await SetupRules.markersTab(reload);
    return h('div', {class: 'stack'}, h('h2', {}, 'Настройки'),
      h('p', {class: 'sub'}, 'Заготовки титана, установки съёмки, правила оценки повторяемости для каждого лазера с линзой и кодовые метки на платах. '
        + 'Лазеры и линзы описываются на экране «Лазеры»; мощность, частота, скорость, импульс, интервал и проходы задаются для каждой платы и слоя.'),
      h('div', {class: 'toolbar'}, h('span', {class: 'spacer'}),
        h('div', {class: 'row', role: 'tablist'}, TABS.map(([id, label]) => h('a', {href: `#/setup?tab=${id}`, class: 'btn' + (id === tab ? ' primary' : ''), role: 'tab', 'aria-selected': id === tab}, label)))),
      body);
  }});
})();
