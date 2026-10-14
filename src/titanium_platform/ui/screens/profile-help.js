/* Блок «Что такое профиль» над формой профиля: простыми словами, без формул, раскрывается по щелчку (REQ-017). */
'use strict';
const ProfileHelp = (() => {
  const {h} = App;

  function card(open = false) {
    const g = GlossaryProfile;
    const constants = Object.values(g.CONSTANTS).map(([name, unit, text]) => h('div', {class: 'stack'}, h('strong', {}, `${name}, ${unit}`), h('p', {class: 'muted'}, text)));
    return h('div', {class: 'card stack'}, h('h3', {}, 'Что такое профиль и зачем он нужен'),
      h('details', {open}, h('summary', {}, 'Объяснение простыми словами'),
        h('div', {class: 'stack', style: 'margin-top:12px'}, ...g.WHAT.map((t) => h('p', {}, t)), h('p', {}, g.AXES), ...constants, h('p', {}, h('strong', {}, g.WHY)))));
  }
  return {card};
})();
