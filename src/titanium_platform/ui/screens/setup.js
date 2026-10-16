/* Hardware/material identities, learning criteria, and registration-mark engraving settings. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, patch, del, toast, fail, confirmBox} = App;
  const TABS = [['laser', 'Лазер + линза'], ['material', 'Титан'], ['rules', 'Оценка повторов'], ['markers', 'Метки для фото']];
  const val = (el) => el.value.trim();

  function laserTab(p, reload, devices, lenses) {
    if (!p) return h('div', {class: 'card'}, h('h3', {}, 'Аппаратная связка'), SetupForms.newProfileForm(reload, devices, lenses));
    const name = h('input', {value: p.name});
    const device = SetupForms.devicePicker(devices, p.device_id), lens = SetupForms.lensPicker(lenses, p.lens_id);
    const save = async () => {
      try {
        await patch('/profiles/' + p.id, {name: val(name), device_id: device.value === '' ? null : +device.value,
          lens_id: lens.value === '' ? null : +lens.value});
        toast('Аппаратная связка сохранена', 'ok'); reload(p.id);
      } catch (e) { fail(e); }
    };
    return h('div', {class: 'stack'},
      h('div', {class: 'grid g3'},
        h('div', {class: 'card'}, h('strong', {}, 'Лазер + конкретная линза'), h('p', {class: 'muted small'}, pill('Идентичность данных', 'ok'))),
        h('div', {class: 'card'}, h('strong', {}, p.linked.observations), h('p', {class: 'muted small'}, 'связанных наблюдений')),
        h('div', {class: 'card'}, h('strong', {}, p.linked.plans + p.linked.plates), h('p', {class: 'muted small'}, 'планов и тестовых плат'))),
      h('div', {class: 'card stack'}, h('h3', {}, 'Аппаратная связка'), field('Название', name),
        h('div', {class: 'grid g2'}, field('Лазер', device), field('Конкретная линза', lens, 'Сохраняется с экспериментом; если линзу заменили, создайте отдельную связку.')),
        p.device ? h('p', {class: 'muted small'}, [link('/devices/' + p.device.id, p.device.name), ` · ${p.device.passport.rated_power_w} Вт`, p.lens ? ` · ${p.lens.name}, ${p.lens.focal_length_mm} мм` : ' · без линзы']) : null,
        h('p', {class: 'muted small'}, 'Мощность, частота, скорость, длительность импульса, интервал линий и число проходов вводятся для каждого теста или слоя. Они не сохраняются в этой связке.'),
        h('div', {class: 'row'}, btn('Сохранить связку', save, 'primary'),
          btn('Удалить связку', () => confirmBox('Удалить связку', 'Связку с историей измерений удалить нельзя.', 'Удалить',
            async () => { await del('/profiles/' + p.id); toast('Связка удалена', 'ok'); reload(); }), 'danger'))),
      h('div', {class: 'card stack'}, h('h3', {}, 'Добавить другую связку'), SetupForms.newProfileForm(reload, devices, lenses)));
  }

  App.register({id: 'profiles', async render(ctx) {
    const profiles = await get('/profiles');
    const tab = TABS.some((t) => t[0] === ctx.query.tab) ? ctx.query.tab : 'laser';
    const p = profiles.find((x) => String(x.id) === ctx.query.profile) || profiles[profiles.length - 1] || null;
    const reload = (id, t) => { location.hash = `#/profiles?tab=${t || tab}${id ? '&profile=' + id : p ? '&profile=' + p.id : ''}`; App.render(); };
    const picker = h('select', {'aria-label': 'Аппаратная связка', disabled: !profiles.length, onChange: (e) => reload(e.target.value)},
      profiles.map((x) => h('option', {value: x.id, selected: p && x.id === p.id}, `${x.name}${x.device ? ` · ${x.device.name}` : ''}${x.lens ? ` · ${x.lens.name}` : ''}`)));
    const [devices, lenses] = tab === 'laser' ? await Promise.all([get('/devices'), get('/lenses')]) : [[], []];
    const body = tab === 'laser' ? laserTab(p, reload, devices, lenses)
      : tab === 'material' ? SetupForms.materialTab(await get('/materials'), reload)
        : tab === 'rules' ? await SetupRules.rulesTab(p, reload) : await SetupRules.markersTab(reload);
    return h('div', {class: 'stack'}, h('h2', {}, 'Лазер, линза и титан'),
      h('p', {class: 'sub'}, 'Здесь хранится идентичность лазера с установленной линзой, запас титана и правила оценки повторяемости. Рабочие параметры задаются для каждого теста и слоя отдельно.'),
      h('div', {class: 'toolbar'}, tab === 'laser' ? h('div', {class: 'f-wrap wide'}, field('Аппаратная связка', picker)) : null, h('span', {class: 'spacer'}),
        h('div', {class: 'row', role: 'tablist'}, TABS.map(([id, label]) => h('a', {href: `#/profiles?tab=${id}${p ? '&profile=' + p.id : ''}`, class: 'btn' + (id === tab ? ' primary' : ''), role: 'tab', 'aria-selected': id === tab}, label)))),
      body);
  }});
})();
