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

  // Вкладки карточки лазера: каждый блок на своём месте, без длинной прокрутки. Адрес: #/devices/:id?tab=...
  const TABS = [['overview', 'Обзор'], ['charts', 'Графики'], ['pulses', 'Формы импульса'], ['report', 'Протокол'], ['lens', 'Линза'], ['controller', 'Настройки лазера'], ['documents', 'Документы']];

  async function detail(id, wanted, section) {
    let d;
    try { d = await get('/devices/' + id); } catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Лазер не найден'), link('/devices', 'К списку лазеров')); }
    const tab = TABS.some((t) => t[0] === wanted) ? wanted : 'overview';
    const refresh = (deviceId) => { location.hash = `#/devices/${deviceId}?tab=${tab}`; App.render(); };
    const openPill = pill('открытых вопросов: ' + d.open_questions.length, d.open_questions.length ? 'warn' : 'ok');
    openPill.dataset.openCount = '1';
    const counts = {lens: d.lens ? 1 : 0, pulses: (d.passport.waveforms || []).length, documents: d.documents.length, controller: ((d.passport.controller || {}).tabs || []).reduce((n, t) => n + t.fields.length, 0), report: ((d.passport.test_report || {}).rows || []).length};
    let body;
    if (tab === 'charts') {
      const charts = await get(`/devices/${id}/charts`), plots = chartsCard(d, charts);
      body = h('div', {class: 'stack'}, DeviceCalc.calculator(d, plots.onPoint), plots.card);
    } else if (tab === 'pulses') {
      body = DeviceReport.waveformsCard(d, await get(`/devices/${id}/charts`)) || h('div', {class: 'card'}, 'Формы импульса в паспорте не записаны');
    } else if (tab === 'report') {
      body = h('div', {class: 'stack'}, DeviceReport.reportCard(d) || h('div', {class: 'card'}, 'Протокол испытаний не загружен'), DeviceView.stepsCard(d));
    } else if (tab === 'lens') {
      body = await DeviceLens.card(d, refresh);
    } else if (tab === 'controller') {
      body = DeviceController.controllerCard(d, refresh, section);
    } else if (tab === 'documents') {
      body = DeviceView.documentsCard(d, refresh);
    } else {
      body = h('div', {class: 'stack'}, DeviceProfileCard.card(d), h('div', {class: 'grid g2'}, DeviceView.passportCard(d), DeviceView.profilesCard(d)),
        h('details', {class: 'card'}, h('summary', {}, h('strong', {}, 'Изменить паспорт: серийный номер, диаметр пятна, ступени, открытые вопросы')), h('div', {style: 'margin-top:14px'}, DeviceForms.editForm(d, refresh))));
    }
    const nav = h('div', {class: 'row', role: 'tablist'}, TABS.map(([key, label]) => h('a', {href: `#/devices/${id}?tab=${key}`, role: 'tab', 'aria-selected': key === tab,
      class: 'btn' + (key === tab ? ' primary' : '')}, label + (counts[key] ? ` · ${counts[key]}` : ''))));
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, d.title), h('p', {class: 'sub'}, [d.manufacturer, d.model].filter(Boolean).join(' · '))), h('span', {class: 'spacer'}),
        openPill, link('/devices', 'Все лазеры'),
        btn('Удалить лазер', () => confirmBox('Удалить лазер', 'Действие необратимо: паспорт и документы будут удалены. Лазер, привязанный к профилю, удалить нельзя.', 'Удалить',
          async () => { await del('/devices/' + id); toast('Лазер удалён', 'ok'); reload(); }), 'danger')),
      nav, body);
  }

  async function list() {
    const devices = await get('/devices');
    const head = h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Лазеры'), h('p', {class: 'sub'}, 'Паспорт каждого лазера: длительности импульса, частоты среза, документы и графики.')));
    const rows = devices.map((d) => h('div', {class: 'card stack'}, h('h3', {}, link('/devices/' + d.id, d.title)),
      h('p', {class: 'muted small'}, `${d.passport.rated_power_w} Вт · ступеней: ${d.passport.pulse_steps.length} · документов: ${d.documents.length} · профилей: ${d.profiles.length}`),
      d.open_questions.length ? pill('открытых вопросов: ' + d.open_questions.length, 'warn') : pill('вопросов нет', 'ok')));
    const templates = h('div', {class: 'card stack'}, h('h3', {}, 'Добавить лазер'), h('div', {class: 'stack'}, await DeviceForms.templateForm(reload),
      h('details', {}, h('summary', {}, 'Другая модель: ввести паспорт вручную'), DeviceForms.createForm(reload))));
    return h('div', {class: 'stack'}, head, devices.length ? h('div', {class: 'grid g2'}, rows) : h('div', {class: 'card empty'}, h('h3', {}, 'Лазеров пока нет'), h('p', {}, 'Добавьте лазер из шаблона или введите паспорт.')), templates);
  }

  App.register({id: 'devices', async render(ctx) { return ctx.arg ? detail(ctx.arg, ctx.query.tab, ctx.query.section) : list(); }});
})();
