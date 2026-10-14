/* Профили и условия измерения: вкладка «Лазер» и сам экран (REQ-010, REQ-009).
   Титан и стенд — setup-forms.js; правила оценки и слой маркеров — setup-rules.js. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, patch, del, toast, fail, modal, confirmBox, facts} = App;
  const TABS = [['laser', 'Лазер'], ['material', 'Титан'], ['stand', 'Стенд'], ['rules', 'Правила оценки'], ['markers', 'Слой маркеров']];
  const val = (el) => el.value.trim();

  function laserTab(p, reload) {
    if (!p) return h('div', {class: 'card'}, h('h3', {}, 'Настройте профиль лазера'),
      h('p', {class: 'muted'}, 'Профиль задаёт константы: длительность импульса, интервал линий и число проходов.'), SetupForms.newProfileForm(reload));
    const name = h('input', {value: p.name}), pw = h('input', {type: 'number', step: 'any', value: p.constants.pulse_width});
    const li = h('input', {type: 'number', step: 'any', value: p.constants.line_interval}), passes = h('input', {type: 'number', step: '1', value: p.constants.passes});
    const links = p.linked, c = p.constants;
    const save = async () => {
      const body = {name: val(name), pulse_width: +pw.value, line_interval: +li.value, passes: +passes.value};
      if (body.pulse_width === c.pulse_width && body.line_interval === c.line_interval && body.passes === c.passes) {
        try { await patch('/profiles/' + p.id, {name: body.name}); toast('Профиль сохранён', 'ok'); reload(p.id); } catch (e) { fail(e); }
        return;
      }
      modal('Новая версия профиля', h('div', {}, h('p', {}, 'Изменение константы создаёт новую версию. Прежние измерения сохранят прежнюю версию и полный вектор параметров.'),
        facts([['Длительность импульса', `${c.pulse_width} → ${body.pulse_width}`], ['Интервал линий', `${c.line_interval} → ${body.line_interval}`], ['Проходы', `${c.passes} → ${body.passes}`]])),
      [{label: 'Отмена', run: (m) => m.close()}, {label: 'Создать версию', cls: 'primary', run: async (m) => {
        const v = await patch('/profiles/' + p.id, {...body, confirm_new_version: true}); m.close(); toast('Создана версия ' + v.version, 'ok'); reload(v.id);
      }}]);
    };
    return h('div', {class: 'stack'},
      h('div', {class: 'grid g3'},
        h('div', {class: 'card'}, h('strong', {}, 'Версия ' + p.version), h('p', {class: 'muted small'}, pill('Сохранённый профиль', 'ok'))),
        h('div', {class: 'card'}, h('strong', {}, links.observations), h('p', {class: 'muted small'}, 'связанных наблюдений')),
        h('div', {class: 'card'}, h('strong', {}, links.plans + links.plates), h('p', {class: 'muted small'}, 'связанных планов и плат'))),
      h('div', {class: 'card stack'}, h('h3', {}, 'Профиль лазера'), field('Название', name),
        h('p', {class: 'muted small'}, 'Переменные оси: ' + p.axes.map((a) => `${a.name} ${a.min}–${a.max} ${a.unit}`).join(' · ') + '. Диапазоны задаёт профиль; это не проверенные пределы оборудования.'),
        h('div', {class: 'grid g3'}, field('Длительность импульса', pw), field('Интервал линий, мм', li), field('Проходы', passes)),
        h('div', {class: 'row'}, btn('Сохранить профиль', save, 'primary'),
          btn('Удалить профиль', () => confirmBox('Удалить версию профиля', 'Действие необратимо. Связанный профиль удалить нельзя: он хранит историю измерений.', 'Удалить',
            async () => { await del('/profiles/' + p.id); toast('Запись удалена', 'ok'); reload(); }), 'danger'))),
      h('div', {class: 'card stack'}, h('h3', {}, 'Новый профиль'), SetupForms.newProfileForm(reload)));
  }

  App.register({id: 'profiles', async render(ctx) {
    const profiles = await get('/profiles');
    const tab = TABS.some((t) => t[0] === ctx.query.tab) ? ctx.query.tab : 'laser';
    const p = profiles.find((x) => String(x.id) === ctx.query.profile) || profiles[profiles.length - 1] || null;
    const reload = (id, t) => { location.hash = `#/profiles?tab=${t || tab}${id ? '&profile=' + id : p ? '&profile=' + p.id : ''}`; App.render(); };
    const picker = h('select', {'aria-label': 'Версия профиля', disabled: !profiles.length, onChange: (e) => reload(e.target.value)},
      profiles.map((x) => h('option', {value: x.id, selected: p && x.id === p.id}, `${x.name} · версия ${x.version}`)));
    const body = tab === 'laser' ? laserTab(p, reload) : tab === 'material' ? SetupForms.materialTab(await get('/materials'), reload)
      : tab === 'stand' ? SetupForms.standTab(await get('/setups'), reload) : tab === 'rules' ? await SetupRules.rulesTab(p, reload) : await SetupRules.markersTab(reload);
    return h('div', {class: 'stack'}, h('h2', {}, 'Профили и условия измерения'), h('p', {class: 'sub'}, 'Лазер, титан, стенд и пороги оценки.'),
      h('div', {class: 'row'}, h('div', {style: 'min-width:260px'}, field('Версия профиля', picker)), h('span', {class: 'spacer'}),
        h('div', {class: 'row', role: 'tablist'}, TABS.map(([id, label]) => h('a', {href: `#/profiles?tab=${id}${p ? '&profile=' + p.id : ''}`, class: 'btn' + (id === tab ? ' primary' : ''), role: 'tab', 'aria-selected': id === tab}, label)))),
      body);
  }});
})();
