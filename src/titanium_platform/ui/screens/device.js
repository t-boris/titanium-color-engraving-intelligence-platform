/* Laser list and detail pages, including specifications, charts, documents and operating point (REQ-017). */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, patch, del, toast, fail, confirmBox} = App;
  const reload = (id) => { location.hash = '#/devices' + (id ? '/' + id : ''); App.render(); };

  function chartsCard(d, charts) {
    const widths = charts.curves.map((c) => c.pulse_width_ns);
    const prefer = widths.includes(200) ? 200 : widths[0];   // 200 ns only if the laser supports this step (DEC-043)
    const pick = h('select', {'aria-label': 'Pulse duration'}, widths.map((w) => h('option', {value: w, selected: w === prefer}, w + ' ns')));
    const power = h('div', {}), energy = h('div', {});
    let mark = null;
    const draw = () => {
      const w = +pick.value;
      power.replaceChildren(DevicePlots.byFrequency(charts, w, 'power', mark && mark.width === w ? mark.power : null));
      energy.replaceChildren(DevicePlots.byFrequency(charts, w, 'energy', mark && mark.width === w ? mark.energy : null));
    };
    pick.addEventListener('change', draw);
    draw();
    const onPoint = (o) => {   // show the calculated point alongside the cutoff frequency
      if (o.cw) { mark = null; return draw(); }
      // Curves show 100% power; place the point on the curve and label its values at the selected power.
      const full = o.set_power_pct / 100, at = ` (${+o.set_power_pct.toPrecision(3)} %)`;
      mark = {width: o.pulse_width_ns,
        power: {x: o.frequency_khz, y: o.output_power_w / full, label: `${+o.output_power_w.toPrecision(3)} W${at}`, color: '#ff9eaf'},
        energy: {x: o.frequency_khz, y: o.pulse_energy_mj / full, label: `${+o.pulse_energy_mj.toPrecision(3)} mJ${at}`, color: '#ff9eaf'}};
      pick.value = String(o.pulse_width_ns); draw();
    };
    const card = h('div', {class: 'card stack'}, h('h3', {}, 'Charts'),
      h('p', {class: 'muted small'}, 'Charts use this laser’s specifications. They are modeled, not measured; a power meter is needed for a measured curve.'),
      h('div', {class: 'grid g2'}, h('div', {}, h('h3', {}, 'Cutoff frequency'), DevicePlots.cutoff(charts)), h('div', {}, h('h3', {}, 'Maximum pulse energy'), DevicePlots.energy(charts))),
      h('div', {class: 'toolbar'}, h('div', {class: 'f-wrap'}, field('Pulse duration', pick))),
      h('div', {class: 'grid g2'}, h('div', {}, h('h3', {}, 'Power by frequency'), power), h('div', {}, h('h3', {}, 'Pulse energy by frequency'), energy)));
    return {card, onPoint};
  }

  // Laser detail tabs use routes of the form #/devices/:id?tab=...
  const TABS = [['overview', 'Overview'], ['experiments', 'Experiments and results'], ['charts', 'Charts'], ['pulses', 'Pulse waveforms'], ['report', 'Test report'], ['lens', 'Lens'], ['controller', 'Laser settings'], ['documents', 'Documents']];

  async function detail(id, wanted, section) {
    let d;
    try { d = await get('/devices/' + id); } catch (e) { return h('div', {class: 'card empty'}, h('h3', {}, 'Laser not found'), link('/devices', 'Back to lasers')); }
    const tab = TABS.some((t) => t[0] === wanted) ? wanted : 'overview';
    const refresh = (deviceId) => { location.hash = `#/devices/${deviceId}?tab=${tab}`; App.render(); };
    const openPill = pill('open questions: ' + d.open_questions.length, d.open_questions.length ? 'warn' : 'ok');
    openPill.dataset.openCount = '1';
    const counts = {lens: d.lens ? 1 : 0, pulses: (d.passport.waveforms || []).length, documents: d.documents.length, controller: ((d.passport.controller || {}).tabs || []).reduce((n, t) => n + t.fields.length, 0), report: ((d.passport.test_report || {}).rows || []).length};
    let body;
    if (tab === 'experiments') {
      const [experiments, lenses] = await Promise.all([get(`/experiments?device_id=${id}`), get('/lenses')]);
      body = DeviceView.experimentsCard(experiments, d, lenses);
    } else if (tab === 'charts') {
      const charts = await get(`/devices/${id}/charts`), plots = chartsCard(d, charts);
      body = h('div', {class: 'stack'}, DeviceCalc.calculator(d, plots.onPoint), plots.card);
    } else if (tab === 'pulses') {
      body = DeviceReport.waveformsCard(d, await get(`/devices/${id}/charts`)) || h('div', {class: 'card'}, 'No pulse waveforms are recorded in the specifications');
    } else if (tab === 'report') {
      body = h('div', {class: 'stack'}, DeviceReport.reportCard(d) || h('div', {class: 'card'}, 'No test report uploaded'), DeviceView.stepsCard(d));
    } else if (tab === 'lens') {
      body = await DeviceLens.card(d, refresh);
    } else if (tab === 'controller') {
      body = DeviceController.controllerCard(d, refresh, section);
    } else if (tab === 'documents') {
      body = DeviceView.documentsCard(d, refresh);
    } else {
      const capabilityResults = await get(`/devices/${id}/capability-results`);
      body = h('div', {class: 'stack'}, DeviceCharacterCard.card(d), DeviceView.capabilityResultsCard(capabilityResults, id),
        DeviceView.passportCard(d),
        h('details', {class: 'card'}, h('summary', {}, h('strong', {}, 'Edit specifications: serial number, spot diameter, steps and open questions')), h('div', {style: 'margin-top:14px'}, DeviceForms.editForm(d, refresh))));
    }
    const technical = new Set(['charts', 'pulses', 'report', 'documents']);
    const tabLink = ([key, label]) => h('a', {href: `#/devices/${id}?tab=${key}`, 'aria-current': key === tab ? 'page' : null,
      class: 'btn' + (key === tab ? ' primary' : '')}, label + (counts[key] ? ` · ${counts[key]}` : ''));
    const nav = h('nav', {class: 'stack device-navigation', 'aria-label': 'Laser sections'},
      h('div', {class: 'row'}, TABS.filter(([key]) => !technical.has(key)).map(tabLink)),
      h('details', {class: 'device-technical', open: technical.has(tab)}, h('summary', {}, 'Technical data'),
        h('div', {class: 'row'}, TABS.filter(([key]) => technical.has(key)).map(tabLink))));
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, d.title), h('p', {class: 'sub'}, [d.manufacturer, d.model].filter(Boolean).join(' · '))), h('span', {class: 'spacer'}),
        openPill, link('/devices', 'All lasers'),
        btn('Delete laser', () => confirmBox('Delete laser', 'This permanently deletes the specifications and documents. A laser with plates, plans or measurements cannot be deleted.', 'Delete',
          async () => { await del('/devices/' + id); toast('Laser deleted', 'ok'); reload(); }), 'danger')),
      nav, body);
  }

  async function list() {
    const devices = await get('/devices');
    const head = h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Lasers'), h('p', {class: 'sub'}, 'Specifications for each laser: pulse durations, cutoff frequencies, documents and charts.')));
    const rows = devices.map((d) => h('div', {class: 'card stack'}, h('h3', {}, link('/devices/' + d.id, d.title)),
      h('p', {class: 'muted small'}, `${d.passport.rated_power_w} W · steps: ${d.passport.pulse_steps.length} · documents: ${d.documents.length} · lens: ${d.lens ? App.lensLabel(d.lens) : 'not installed'}`),
      d.open_questions.length ? pill('open questions: ' + d.open_questions.length, 'warn') : pill('no open questions', 'ok')));
    const templates = h('div', {class: 'card stack'}, h('h3', {}, 'Add laser'), h('div', {class: 'stack'}, await DeviceForms.templateForm(reload),
      h('details', {}, h('summary', {}, 'Another model: enter specifications manually'), DeviceForms.createForm(reload))));
    return h('div', {class: 'stack'}, head, devices.length ? h('div', {class: 'grid g2'}, rows) : h('div', {class: 'card empty'}, h('h3', {}, 'No lasers yet'), h('p', {}, 'Add a laser from a template or enter its specifications.')), templates);
  }

  App.register({id: 'devices', async render(ctx) { return ctx.arg ? detail(ctx.arg, ctx.query.tab, ctx.query.section) : list(); }});
})();
