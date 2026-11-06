/* Color map and parameter selection for a laser and lens, with calibrated and RAW observations. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, post, modal, num, labText, swatch, facts} = App;
  const {STAGE, stab, params} = KnowledgeView;
  const STAGES = Object.keys(STAGE);                       // measured … production: the order in which an entry earns trust
  const SVG = 'http://www.w3.org/2000/svg';
  const PAIR_STATUS = {'Awaiting check': 'awaiting review', 'Needs correction': 'needs correction', 'Ready to accept': 'ready to accept',
    Accepted: 'accepted'};
  // what a RAW layer was engraved for
  const ROLE = {test: 'Test area', witness: 'Cleaning witness', labels: 'Markers and labels'};
  const roleOf = (s) => (s.role === 'pre-test cleaning witness' ? 'witness' : s.role === 'registration, QR and engraved labels' ? 'labels' : 'test');

  const SET_KEY = 'lm.set', TAB_KEY = 'lm.tab';
  const stored = (key) => { try { return localStorage.getItem(key); } catch (_) { return null; } };
  const keep = (key, value) => { try { localStorage.setItem(key, value); } catch (_) { /* a viewer without storage starts on the first set */ } };

  /** ``fit`` draws a square map that fills its box (the one-screen page); otherwise the map keeps its fixed proportions. */
  function mapPlot(samples, {fit = false} = {}) {
    if (!samples.length) return h('p', {class: 'muted'}, 'No measured colors');
    const W = 520, H = fit ? 520 : 360, a = samples.map((s) => s.lab[1]), b = samples.map((s) => s.lab[2]);
    const lo = [Math.min(...a) - 8, Math.min(...b) - 8], hi = [Math.max(...a) + 8, Math.max(...b) + 8];
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Measured colors in the a-b plane');
    svg.style.cssText = fit ? 'width:100%;height:100%' : 'width:100%;max-width:720px';   // look comes from styles.css (svg[role=img])
    samples.forEach((s) => {
      const c = document.createElementNS(SVG, 'circle');
      c.setAttribute('cx', 20 + ((s.lab[1] - lo[0]) / (hi[0] - lo[0])) * (W - 40));
      c.setAttribute('cy', H - 20 - ((s.lab[2] - lo[1]) / (hi[1] - lo[1])) * (H - 40));
      c.setAttribute('r', 6 + Math.min(8, (s.engravings || 1) * 2));
      c.setAttribute('fill', swatch(s.lab).style.background || '#888');
      c.setAttribute('stroke', s.available ? '#fff' : '#777');
      if (!s.available) c.setAttribute('stroke-dasharray', '3 2');
      const t = document.createElementNS(SVG, 'title');
      t.textContent = `${s.name ? s.name + ' · ' : ''}${labText(s.lab)} · engravings ${s.engravings || 1}`;
      c.append(t);
      svg.append(c);
    });
    return svg;
  }

  function predictDialog(pick) {
    // model.predict_for_lab refuses a colour outside color.valid_lab (L 0 to 100, a and b from -128 to 127): the dialog says so beside the box and keeps what was typed
    const form = Forms.create();
    const fields = [form.add('L', 'L', Forms.numberInput(Forms.QUANTITIES.predictL, {value: 50}), {quantity: 'predictL', required: true}),
      form.add('a', 'a', Forms.numberInput(Forms.QUANTITIES.predictAB, {value: 0}), {quantity: 'predictAB', required: true}),
      form.add('b', 'b', Forms.numberInput(Forms.QUANTITIES.predictAB, {value: 0}), {quantity: 'predictAB', required: true})];
    const out = h('div', {class: 'stack'});
    modal('Target color', h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, ...fields), form.error, out), [
      {label: 'Close', run: (m) => m.close()},
      {label: 'Find parameters', cls: 'primary', run: async () => {
        const v = form.collect();
        if (!v) return;
        let r;
        try { r = await post('/predict', {device_id: pick.deviceId(), lens_id: pick.lensId(), lab: [v.L, v.a, v.b]}); } catch (e) { form.fail(e); return; }
        out.replaceChildren(!r.available
          ? h('div', {class: 'alert warn'}, 'Insufficient data for a prediction: parameters are not offered without confidence, error, and stability estimates.')
          : h('div', {class: 'stack'}, r.outside_coverage ? h('div', {class: 'alert warn'}, 'Outside measured color coverage') : h('div', {class: 'alert ok'}, 'Within measured coverage'),
            facts([['Predicted color', h('span', {}, swatch(r.lab), labText(r.lab))], ['ΔE distance to target', num(r.distance_to_target)], ['Parameters', params(r.parameters)],
              ['Confidence', num(r.confidence)], ['Expected ΔE error', num(r.expected_delta_e)], ['Stability', stab(r.stability)]])));
      }}]);
  }

  function variantSettings(p) {
    const source = p.source_settings || {};
    const wobble = source.wobbleEnable?.Value;
    return [
      params(p),
      `Q-Pulse ${p.pulse_width == null ? 'not recorded' : p.pulse_width + ' ns'}`,
      p.line_interval == null ? null : `interval ${p.line_interval} mm`,
      `${p.passes ?? '—'} passes`,
      p.global_passes == null ? null : `global ${p.global_passes}×`,
      p.bidirectional == null ? null : `bidirectional ${p.bidirectional ? 'yes' : 'no'}`,
      p.cross_hatch == null ? null : `cross-hatch ${p.cross_hatch ? 'yes' : 'no'}`,
      p.scan_angle == null ? null : `angle ${p.scan_angle}°`,
      p.angle_increment == null ? null : `angle increment ${p.angle_increment}°`,
      wobble == null ? null : wobble === '1'
        ? `Wobble: size ${source.wobbleSize?.Value ?? '—'} mm, interval ${source.wobbleStep?.Value ?? '—'} mm`
        : 'Wobble off',
    ].filter(Boolean).join(' · ');
  }

  /** One line of a compact list: the main part (swatch, name, pills) and, under it, the figures that used to be table columns. */
  const item = (top, sub, cls = '') => h('div', {class: 'lm-item ' + cls}, h('div', {class: 'lm-item-top'}, ...top),
    sub && sub.length ? h('div', {class: 'lm-item-sub'}, ...sub) : null);
  const dot = (parts) => parts.filter((x) => x != null && x !== '').join(' · ');

  /** What the page shows of one set of camera-relative (RAW) observations: its heading, the map, the cautions and the tabs. */
  function relativeView(set) {
    const samples = set.samples || [];
    const variants = set.color_variants || [];
    const plotSamples = samples.map((s) => ({...s, engravings: 1, available: false}));
    const findingRows = (set.findings || []).map((f) => item([swatch(f.lab), h('strong', {}, `${f.label} · ${f.name}`), h('span', {class: 'muted small'}, labText(f.lab))],
      [dot([params(f.parameters), `ΔE from cleaned surface ${f.delta_e == null ? '—' : num(f.delta_e)}`])]));
    // every measured layer is one line of a short list; its figures, notes and measured parts open under the line
    const partsOf = (s) => (s.submeasurements || []).filter((sub) => sub.measured_lab);
    const part = (s, sub) => item([swatch(sub.measured_lab), h('strong', {}, `${s.name} / ${sub.name}`), h('span', {class: 'muted small'}, labText(sub.measured_lab))],
      [dot(['Layer part', params(s.parameters), `ΔE from cleaned surface ${num(sub.delta_e_from_clean_witness)}`, `pixels ${sub.pixels == null ? '—' : num(sub.pixels, 0)}`])], 'lm-sub');
    const contrast = (s) => s.delta_e_from_clean_witness ?? -1;            // the witness itself has none: last
    const layerList = () => App.list({id: 'lm.layers.' + set.pair_id, items: samples.map((s, at) => ({s, at})), key: (x) => x.at,
      search: ({s}) => `${s.name} ${s.relative_appearance || ''} ${ROLE[roleOf(s)]}`,
      row: ({s}) => [swatch(s.lab), h('span', {class: 'lst-text', title: dot([s.name, s.relative_appearance])}, dot([s.name, s.relative_appearance])),
        roleOf(s) === 'test' ? null : pill(ROLE[roleOf(s)]),
        s.delta_e_from_clean_witness == null ? null : h('span', {class: 'small'}, `ΔE ${num(s.delta_e_from_clean_witness, 1)}`),
        partsOf(s).length ? h('span', {class: 'muted small'}, `parts ${partsOf(s).length}`) : null],
      details: ({s}) => h('div', {class: 'stack small'},
        h('p', {}, dot([ROLE[roleOf(s)], labText(s.lab), params(s.parameters), `ΔE from cleaned surface ${num(s.delta_e_from_clean_witness)}`,
          `pixels ${s.pixels == null ? '—' : num(s.pixels, 0)}`])),
        ...(s.notes || []).map((note) => h('p', {class: 'muted'}, I18N.tr(note))),
        partsOf(s).length ? h('div', {class: 'lm-list'}, ...partsOf(s).map((sub) => part(s, sub))) : null),
      filters: [{key: 'role', label: 'Layer role', options: Object.entries(ROLE), test: ({s}, v) => roleOf(s) === v}],
      sorts: [['order', 'In order', (p, q) => p.at - q.at],
        ['contrast', 'Most different from cleaned surface', (p, q) => contrast(q.s) - contrast(p.s) || p.at - q.at],
        ['light', 'Lightest first', (p, q) => q.s.lab[0] - p.s.lab[0] || p.at - q.at]],
      empty: 'No layers match the selected filters.'}).el;
    const material = [set.material?.name, set.material?.grade, set.material?.batch && `batch ${set.material.batch}`].filter(Boolean).join(' · ');
    // every colour variant is one line of a short list too; its settings and the link to the photograph open under the line
    const variantList = () => App.list({id: 'lm.variants.' + set.pair_id, items: variants.map((v, at) => ({v, at})), key: (x) => x.at,
      search: ({v}) => `${v.name} ${variantSettings(v.parameters)}`,
      row: ({v}) => [swatch(v.lab), h('span', {class: 'lst-text', title: v.name}, v.name), h('span', {class: 'muted small'}, labText(v.lab)),
        h('span', {class: 'small'}, `ΔE ${num(v.delta_e_from_clean_witness, 1)}`), v.settings_complete ? null : pill('incomplete settings', 'warn')],
      details: ({v}) => h('div', {class: 'stack small'}, h('p', {}, variantSettings(v.parameters)),
        h('p', {class: 'muted'}, `Difference from the cleaned background in this photo: ΔE ${num(v.delta_e_from_clean_witness, 1)}`, v.settings_complete ? '' : ' · incomplete settings'),
        link('/analysis/' + set.pair_id, 'Photo and measurements')),
      sorts: [['order', 'In order', (p, q) => p.at - q.at],
        ['contrast', 'Most different from cleaned surface', (p, q) => (q.v.delta_e_from_clean_witness ?? -1) - (p.v.delta_e_from_clean_witness ?? -1) || p.at - q.at],
        ['light', 'Lightest first', (p, q) => q.v.lab[0] - p.v.lab[0] || p.at - q.at]],
      empty: 'No variants match the selected filters.'}).el;
    const alerts = [
      set.provisional ? h('div', {class: 'alert warn'}, `Results are measured but not yet accepted: ${set.masks_reviewed ? 'masks reviewed' : 'mask overlay needs review'}; pair status: ${PAIR_STATUS[set.status] || set.status}. These data are provisional.`) : null,
      ...(set.warnings || []).map((warning) => h('div', {class: 'alert warn', role: 'status'}, I18N.tr(warning))),
      h('div', {class: 'alert warn'}, 'These hues and Lab values are relative to this RAW photo. The map shows them for comparison; they are excluded from standard color predictions and are not compared across photo sessions.'),
      set.provisional ? link('/ingest?pair=' + set.pair_id, 'Review layers and accept pair') : null];
    const list = (rows, empty) => (rows.length ? h('div', {class: 'lm-list'}, ...rows) : h('p', {class: 'muted'}, empty));
    return {
      title: `${set.provisional ? 'Provisional RAW observations' : 'RAW observations'} · pair ${set.pair_id}`,
      sub: `${set.photo_name || 'photo'} · ${set.lightburn_name || 'LightBurn'}${material ? ` · ${material}` : ''}`,
      plot: mapPlot(plotSamples, {fit: true}), plotTitle: 'Relative a* × b* map', alerts,
      tabs: [['seen', `What is visible (${findingRows.length})`, h('div', {class: 'stack'}, h('h4', {}, 'What is visible in this pair'), list(findingRows, 'No data'))],
        ['variants', `Variants (${variants.length})`, h('div', {class: 'stack'}, h('h4', {}, `Color variants from test squares · ${variants.length}`),
          variants.length ? h('p', {class: 'muted small'}, 'Each variant is linked to a specific area, LightBurn settings, and this photo. The on-screen swatch is approximate; repeat with a reference chart before using a recipe.') : null,
          variants.length ? variantList() : h('p', {class: 'muted'}, 'No data'))],
        ['layers', `All layers (${samples.length})`, h('div', {class: 'stack'}, h('h4', {}, `All measured layers (${samples.length})`),
          samples.length ? layerList() : h('p', {class: 'muted'}, 'No data'))]]};
  }

  /** The calibrated observations the forecast is made from: the map of every sample and the model of colour parameters beside it.
      The model is a short list: one line per entry (its settings and colour, stage, doubt, expected error), the figures under the line
      on a click and «Open» to the entry's own page; the choices are kept under ``listId`` (one laser and lens). */
  function calibratedView(map, know, listId) {
    const rank = (k) => STAGES.indexOf(k.stage);
    const taskOf = (k) => (k.summary && k.summary.task && k.summary.task.kind) || '';
    const error = (k) => (k.summary && k.summary.available ? k.summary.expected_delta_e : Infinity);          // no estimate: last
    const engravings = (k) => (k.summary ? k.summary.independent_engravings : 0);
    const lightness = (k) => (k.summary ? k.summary.lab[0] : -1);
    const tasks = [...new Set(know.map(taskOf).filter(Boolean))];
    const model = () => App.list({id: listId, items: know, key: (k) => k.id,
      search: (k) => [params(k.parameters), labText(k.summary && k.summary.lab), STAGE[k.stage], taskOf(k) && Tasks.name(taskOf(k))].join(' '),
      row: (k) => {
        const s = k.summary, text = dot([params(k.parameters), s && labText(s.lab)]);
        return [s ? swatch(s.lab) : null, h('span', {class: 'lst-text', title: text}, text),
          pill(STAGE[k.stage] || k.stage, k.stage === 'production' ? 'ok' : ''), k.questioned ? pill('questioned', 'bad') : null,
          s && s.available ? h('span', {class: 'small'}, `ΔE ${num(s.expected_delta_e, 1)}`) : null];
      },
      details: (k) => {
        const s = k.summary;
        // REQ-001 of ux-evidence-summaries-p0: the signals first (every observation of an entry is chart-corrected), the figures in a fold
        return h('div', {class: 'stack small'}, h('p', {}, variantSettings(k.parameters)),
          s ? EvidenceSummary.summary({...s, measurement: 'calibrated', engravings: s.independent_engravings}) : null,
          EvidenceSummary.disclosure('Numbers: Lab color, confidence, ΔE error, stability',
            h('p', {}, dot([s && labText(s.lab), `independent ${s ? s.independent_engravings : 0}`, `confidence ${s && s.available ? num(s.confidence) : '—'}`,
              `ΔE error ${s && s.available ? num(s.expected_delta_e) : '—'}`, `stability ${s ? stab(s.stability) : '—'}`]))),
          taskOf(k) ? h('p', {class: 'muted'}, `Task: ${Tasks.name(taskOf(k))}`) : null,
          k.questioned && k.doubt ? h('p', {}, h('strong', {}, 'Questioned. '), I18N.tr(k.doubt.reason)) : null);
      },
      actions: (k) => [h('a', {class: 'btn btn-small', href: '#/knowledge/' + k.id}, 'Open')],
      filters: [{key: 'stage', label: 'Stage', options: Object.entries(STAGE), test: (k, v) => k.stage === v},
        {key: 'questioned', label: 'Questioned', select: true, options: [['yes', 'yes'], ['no', 'no']], test: (k, v) => k.questioned === (v === 'yes')},
        ...(tasks.length ? [{key: 'task', label: 'Task', select: true, options: tasks.map((t) => [t, Tasks.name(t)]), test: (k, v) => taskOf(k) === v}] : [])],
      sorts: [['stage', 'By stage', (p, q) => rank(q) - rank(p) || p.id - q.id],
        ['error', 'Lowest ΔE error', (p, q) => (error(p) === error(q) ? 0 : error(p) - error(q)) || p.id - q.id],
        ['engravings', 'Most engravings', (p, q) => engravings(q) - engravings(p) || p.id - q.id],
        ['light', 'Lightest first', (p, q) => lightness(q) - lightness(p) || p.id - q.id],
        ['newest', 'Newest first', (p, q) => q.id - p.id]],
      empty: 'No records match the selected filters.'}).el;
    return {title: 'Calibrated observations for prediction', sub: `${map.samples.length} measured colors`, plot: mapPlot(map.samples, {fit: true}), plotTitle: null,
      alerts: [h('p', {class: 'muted small'}, 'Dashed marks indicate sets without repeatability estimates. Colors are a screen representation of Lab.')],
      model: {count: know.length, body: know.length ? model() : h('p', {class: 'muted'}, 'No data')}};
  }

  App.register({id: 'colors', async render(ctx) {
    if (ctx.id === 'knowledge') return KnowledgeView.render(ctx.arg);
    if (!ctx.query.device) return ColorMap.render(ctx);     // the general map; ?device=&lens= opens the model of one laser and lens
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'No measured colors'), link('/devices', 'Lasers'), ' ', link('/ingest', 'Add observation'));
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens, onChange: () => { location.hash = '#/colors?' + pick.route(); }});
    const [map, know] = await Promise.all([get('/color-model?' + pick.query()), get('/knowledge?' + pick.query())]);
    const head = h('div', {class: 'os-head lm-head'}, h('a', {class: 'btn btn-small', href: '#/colors'}, '← Color map'),
      h('div', {class: 'lm-title'}, h('h2', {}, 'Color map and parameter selection'), h('p', {class: 'sub'}, 'Data from different lasers and lenses, including unknown lenses, are not combined.')),
      h('span', {class: 'spacer'}), h('div', {class: 'lm-pick'}, field('Laser', pick.laser), field('Lens', pick.lens)),
      btn('Target color', () => predictDialog(pick), 'primary'), h('a', {class: 'btn btn-small', href: '#/designer?' + pick.route()}, 'Plan experiment'));
    const relativeSets = map.camera_relative_sets || [];
    if (!map.samples.length && !relativeSets.length) return h('div', {class: 'os lm'}, head,
      h('div', {class: 'card empty'}, h('h3', {}, 'No reviewed measurements for this laser and lens yet'), link('/ingest', 'Add experiment photo')));

    // the sets in the order of the old page: the calibrated observations, then every RAW pair
    const sets = [...(map.samples.length ? [{id: 'calibrated', title: 'Calibrated observations', note: `measured colors ${map.samples.length}${know.length ? ` · in model ${know.length}` : ''}`, view: () => calibratedView(map, know, 'lm.knowledge.' + pick.route())}] : []),
      ...relativeSets.map((set) => ({id: 'pair-' + set.pair_id, title: `${set.provisional ? 'Provisional · ' : ''}pair ${set.pair_id}`,
        note: `${set.photo_name || 'photo'} · layers ${(set.samples || []).length} · variants ${(set.color_variants || []).length}`, view: () => relativeView(set)}))];
    // a laser with many RAW pairs has many sets: a search and pages of twenty, the set on the screen kept in view (ux-growing-collections-p0, REQ-002, REQ-003)
    let current = null;
    const setList = SetList.list(sets, {selected: () => current, onSelect: (id) => select(id)});
    const left = h('section', {class: 'os-col lm-left', 'aria-label': 'Observation sets'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Sets'), pill(sets.length)), h('div', {class: 'os-scroll'}, h('div', {class: 'lm-sets'}, setList.el)));
    const centre = h('section', {class: 'os-col lm-centre'}), right = h('section', {class: 'os-col lm-right'});

    function select(id) {
      const set = sets.find((s) => s.id === id) || sets[0];
      current = set.id;
      setList.refresh();                                         // the pressed line follows
      keep(SET_KEY, set.id);
      const view = set.view();
      fill(centre, h('div', {class: 'os-col-head'}, h('div', {class: 'lm-set-title'}, h('h3', {}, view.title), h('p', {class: 'muted small'}, view.sub)), view.plotTitle ? pill(view.plotTitle) : null),
        h('div', {class: 'lm-stage'}, h('div', {class: 'lm-plot'}, view.plot), h('div', {class: 'lm-alerts'}, ...view.alerts)));
      if (view.model) {
        fill(right, h('div', {class: 'os-col-head'}, h('h3', {}, 'Color parameter model'), pill(view.model.count)), h('div', {class: 'os-scroll'}, view.model.body));
      } else {
        const tabs = App.tabs(view.tabs, {initial: view.tabs[0][0], remember: TAB_KEY, label: 'Set tables', prefix: 'lm-tab'});
        fill(right, tabs.list, h('div', {class: 'os-scroll'}, ...tabs.panels));
      }
    }
    select(sets.some((s) => s.id === stored(SET_KEY)) ? stored(SET_KEY) : sets[0].id);
    return h('div', {class: 'os lm'}, head,
      map.unstable.length ? h('div', {class: 'alert warn lm-unstable'}, 'Unstable sets: ' + map.unstable.map((u) => `${u.parameters.power}/${u.parameters.frequency}/${u.parameters.speed}`).join(', ')) : null,
      h('div', {class: 'os-body lm-body'}, left, centre, right));
  }});
})();
