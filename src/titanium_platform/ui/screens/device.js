/* Экран «Лазеры»: список, карточка лазера с паспортом, графиками, документами и расчётом рабочей точки (REQ-017). */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, patch, del, toast, fail, confirmBox} = App;
  const reload = (id) => { location.hash = '#/devices' + (id ? '/' + id : ''); App.render(); };

  function chartsCard(d, charts) {
    const widths = charts.curves.map((c) => c.pulse_width_ns);
    const prefer = (d.profiles[0] && d.profiles[0].pulse_width) || 200;
    const pick = h('select', {'aria-label': 'Длительность импульса'}, widths.map((w) => h('option', {value: w, selected: w === prefer}, w + ' нс')));
    const power = h('div', {}), energy = h('div', {});
    let mark = null;
    const draw = () => {
      const w = +pick.value;
      power.replaceChildren(DevicePlots.byFrequency(charts, w, 'power', mark && mark.width === w ? mark.power : null));
      energy.replaceChildren(DevicePlots.byFrequency(charts, w, 'energy', mark && mark.width === w ? mark.energy : null));
    };
    pick.addEventListener('change', draw);
    draw();
    const onPoint = (o) => {   // точка из расчёта: на графиках она видна рядом с частотой среза
      if (o.cw) { mark = null; return draw(); }
      // Кривые — при 100 % мощности, поэтому точка ставится на кривую, а в подписи — значения при заданной мощности.
      const full = o.set_power_pct / 100, at = ` (${+o.set_power_pct.toPrecision(3)} %)`;
      mark = {width: o.pulse_width_ns,
        power: {x: o.frequency_khz, y: o.output_power_w / full, label: `${+o.output_power_w.toPrecision(3)} Вт${at}`, color: '#ff9eaf'},
        energy: {x: o.frequency_khz, y: o.pulse_energy_mj / full, label: `${+o.pulse_energy_mj.toPrecision(3)} мДж${at}`, color: '#ff9eaf'}};
      pick.value = String(o.pulse_width_ns); draw();
    };
    const card = h('div', {class: 'card stack'}, h('h3', {}, 'Графики'),
      h('p', {class: 'muted small'}, 'Все графики строятся из паспорта этого лазера. Расчёт по паспорту, не измерение: для измеренной кривой нужен измеритель мощности.'),
      h('div', {class: 'grid g2'}, h('div', {}, h('h3', {}, 'Частота среза'), DevicePlots.cutoff(charts)), h('div', {}, h('h3', {}, 'Наибольшая энергия импульса'), DevicePlots.energy(charts))),
      h('div', {class: 'toolbar'}, h('div', {class: 'f-wrap'}, field('Длительность импульса', pick))),
      h('div', {class: 'grid g2'}, h('div', {}, h('h3', {}, 'Мощность по частоте'), power), h('div', {}, h('h3', {}, 'Энергия импульса по частоте'), energy)));
    return {card, onPoint};
  }

  async function detail(id) {
    let d;
    try { d = await get('/devices/' + id); } catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Лазер не найден'), link('/devices', 'К списку лазеров')); }
    const charts = await get(`/devices/${id}/charts`), plots = chartsCard(d, charts);
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, d.name), h('p', {class: 'sub'}, [d.manufacturer, d.model].filter(Boolean).join(' · '))), h('span', {class: 'spacer'}), link('/devices', 'Все лазеры'),
        btn('Удалить лазер', () => confirmBox('Удалить лазер', 'Действие необратимо: паспорт и документы будут удалены. Лазер, привязанный к профилю, удалить нельзя.', 'Удалить',
          async () => { await del('/devices/' + id); toast('Лазер удалён', 'ok'); reload(); }), 'danger')),
      h('div', {class: 'grid g2'}, DeviceView.passportCard(d), DeviceView.profilesCard(d)),
      DeviceCalc.calculator(d, plots.onPoint), plots.card, DeviceReport.waveformsCard(d, charts), DeviceView.stepsCard(d), DeviceReport.reportCard(d),
      DeviceController.controllerCard(d), DeviceView.documentsCard(d, reload),
      h('div', {class: 'card stack'}, h('h3', {}, 'Изменить паспорт'), DeviceForms.editForm(d, reload)));
  }

  async function list() {
    const devices = await get('/devices');
    const head = h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Лазеры'), h('p', {class: 'sub'}, 'Паспорт каждого лазера: длительности импульса, частоты среза, документы и графики.')));
    const rows = devices.map((d) => h('div', {class: 'card stack'}, h('h3', {}, link('/devices/' + d.id, d.name)),
      h('p', {class: 'muted small'}, `${d.passport.rated_power_w} Вт · ступеней: ${d.passport.pulse_steps.length} · документов: ${d.documents.length} · профилей: ${d.profiles.length}`),
      (d.passport.open_items || []).length ? pill('открытых вопросов: ' + d.passport.open_items.length, 'warn') : null));
    const templates = h('div', {class: 'card stack'}, h('h3', {}, 'Добавить лазер'), h('div', {class: 'stack'}, await DeviceForms.templateForm(reload),
      h('details', {}, h('summary', {}, 'Другая модель: ввести паспорт вручную'), DeviceForms.createForm(reload))));
    return h('div', {class: 'stack'}, head, devices.length ? h('div', {class: 'grid g2'}, rows) : h('div', {class: 'card empty'}, h('h3', {}, 'Лазеров пока нет'), h('p', {}, 'Добавьте лазер из шаблона или введите паспорт.')), templates);
  }

  App.register({id: 'devices', async render(ctx) { return ctx.arg ? detail(ctx.arg) : list(); }});
})();
