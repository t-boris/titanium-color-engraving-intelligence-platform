/* Experiment planner: reproducible proposals, acceptance, and measured outcomes. AI explanations are optional. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, post, toast, fail, modal, table, num, labText, swatch, facts} = App;
  const REASON = {target: 'Target color', instability: 'Instability', uncertainty: 'High uncertainty', gap: 'Coverage gap', repeat: 'Repeat'};
  const STATUS = {proposed: ['Proposed', ''], accepted: ['Accepted: awaiting plate photos', 'warn'], rejected: ['Rejected', 'bad'], done: ['Completed', 'ok']};
  const TASK = {line: 'lines', fill: 'fills', tonal_image: 'tonal image'};
  const when = (iso) => (iso ? new Date(iso).toLocaleString('en-US', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');
  const params = (p) => `${num(p.power, 1)}% · ${num(p.frequency, 0)} kHz · ${num(p.speed, 0)} mm/s · ${num(p.pulse_width, 0)} ns · interval ${num(p.line_interval, 4)} mm · ${p.passes} passes`;
  const stockName = (s) => [s.name, s.grade, s.batch].filter(Boolean).join(' · ') || 'unnamed titanium';

  function plateDialog(prop, reload) {
    const f = Forms.create();
    const Q = Forms.QUANTITIES;
    const size = (value) => Forms.numberInput(Q.cellSize, {value});
    const cells = [f.add('cw', 'Cell width', size(6), {quantity: 'cellSize', required: true}), f.add('ch', 'Cell height', size(5), {quantity: 'cellSize', required: true}),
      f.add('gap', 'Gap', Forms.numberInput(Q.gap, {value: 1}), {quantity: 'gap', required: true})];
    modal('Accept proposal and create plates', h('div', {class: 'stack'}, h('p', {}, 'For each proposed speed, a plate covers every combination of proposed powers and frequencies, with surface cleaning first. Extra grid intersections are marked and are not planner recommendations. Plates use the lens currently installed on the laser; it must match the proposal. No measurements are created.'),
      h('div', {class: 'grid g3'}, ...cells), f.error), [
      {label: 'Cancel', run: (m) => m.close()},
      {label: 'Accept and create plates', cls: 'primary', run: async (m) => {
        const v = f.collect();
        if (!v) return;                                   // the dialog stays open with the reason beside the box
        let made;
        try { made = await post(`/designer/proposals/${prop.id}/accept`, {cell_width: v.cw, cell_height: v.ch, gap: v.gap}); } catch (e) { f.fail(e); return; }
        m.close(); toast(`Proposal accepted; plates created: ${made.plates.length}`, 'ok'); reload();
      }}]);
  }

  function rejectDialog(prop, reload) {
    const f = Forms.create();
    const note = f.add('note', 'Reason', h('input', {placeholder: 'for example: these settings were tested on another stock'}), {raw: true, help: 'optional'});
    modal('Reject proposal', h('div', {class: 'stack'}, h('p', {}, 'A rejected proposal remains in the history; plates cannot be created from it.'), note, f.error), [
      {label: 'Cancel', run: (m) => m.close()},
      {label: 'Reject', cls: 'danger', run: async (m) => {
        const v = f.collect();
        if (!v) return;
        try { await post(`/designer/proposals/${prop.id}/reject`, {note: v.note}); } catch (e) { f.fail(e); return; }
        m.close(); toast('Proposal rejected', 'ok'); reload();
      }}]);
  }

  /** Measured color on each accepted photo and the target check. */
  function outcome(prop, r) {
    if (!r || !r.plate_id) return h('span', {class: 'muted'}, prop.boards.length ? 'cell is not on the plates' : 'plates have not been created yet');
    if (!r.measured.length) return h('span', {class: 'muted'}, 'not yet measured');
    return h('div', {class: 'stack small'}, r.measured.map((m) => h('span', {}, swatch(m.lab), ' ', labText(m.lab), ' · ', link('/analysis/' + m.pair_id, 'photo #' + m.pair_id),
      m.comparable ? null : ' · without reference chart',
      m.target_check && m.target_check.delta_e != null ? ` · ΔE to target ${num(m.target_check.delta_e, 1)}${m.target_check.within_tolerance == null ? '' : m.target_check.within_tolerance ? ' (within tolerance)' : ' (outside tolerance)'}` : null,
      m.delta_e_to_repeated_recipe != null ? ` · ΔE from first engraving ${num(m.delta_e_to_repeated_recipe, 1)}` : null)));
  }

  function platesBlock(prop) {
    if (!prop.plates.length) return null;
    return h('div', {class: 'stack'}, h('h4', {}, 'Plates and their photos'), table(['Plate', 'Plan', 'Photos'], prop.plates.map((p) => [
      `${p.experiment_id} · speed ${num(p.speed, 0)} mm/s` + (p.deleted ? ' · deleted' : ''),
      p.plan_id ? link('/plans/' + p.plan_id, 'plan #' + p.plan_id) : '—',
      p.pairs.length ? h('div', {class: 'row'}, p.pairs.map((x) => h('span', {}, link(x.status === 'Accepted' ? '/analysis/' + x.id : '/ingest?pair=' + x.id, 'photo #' + x.id), ' ',
        x.status === 'Accepted' ? pill('accepted', 'ok') : pill('awaiting review', 'warn'))))
        : (p.plan_id ? link('/ingest?plan=' + p.plan_id, 'upload photo') : '—')])));
  }

  function explanationBlock(prop, reload) {
    const shown = prop.explanation ? h('div', {class: 'alert'}, h('strong', {}, 'AI explanation: hypotheses, not measurements. '), prop.explanation) : null;
    if (!prop.explanation_available) {
      return h('div', {class: 'stack'}, shown, h('p', {class: 'muted small'}, 'AI explanation is unavailable because no model key is configured. The proposal works without it.'));
    }
    return h('div', {class: 'stack'}, shown, h('div', {class: 'row'}, btn(prop.explanation ? 'Refresh AI explanation' : 'Get AI explanation', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await post(`/designer/proposals/${prop.id}/explanation`); toast('Explanation received', 'ok'); reload(); }
      catch (e) { fail(e); self.disabled = false; }
    }), h('span', {class: 'muted small'}, 'The model explains the proposal and suggests hypotheses; it does not change settings or data.')));
  }

  /** The parameter sets of a proposal (up to 40), a set a line: its number, settings, reason, target and whether it is measured; why it was
      chosen, its utility, target and measured result under the line (REQ-022 AC5); in the planner's order or by utility, twenty at a time (DEC-090). */
  function setsList(prop) {
    const results = new Map((prop.results || []).map((r) => [r.index, r]));
    const sets = prop.parameters.map((set, i) => ({set, i, result: results.get(i)}));
    const measured = ({result}) => (result && result.measured ? result.measured.length : 0);
    const target = (x) => (x.target_id ? 'target #' + x.target_id + (x.estimated_distance_to_target != null ? ` (predicted ΔE ${num(x.estimated_distance_to_target)})` : '') : '—');
    return App.list({items: sets, key: (s) => s.i,
      row: (s) => [h('span', {class: 'muted small'}, `#${s.i + 1}`), h('span', {class: 'lst-text'}, params(s.set)), pill(REASON[s.set.reason] || s.set.reason),
        s.set.target_id ? h('span', {class: 'small'}, 'target #' + s.set.target_id) : null, measured(s) ? pill(`measured: photos ${measured(s)}`, 'ok') : null],
      details: ({set: x, result}) => facts([['Why selected', x.rationale ? I18N.tr(x.rationale) : '—'], ['Utility', num(x.utility)], ['Target', target(x)],
        ['Result', outcome(prop, result)]]),
      filters: [{key: 'reason', label: 'Reason', options: Object.entries(REASON), test: (s, v) => s.set.reason === v},
        ...(sets.some(measured) ? [{key: 'measured', label: 'Measured', options: [['yes', 'measured'], ['no', 'not yet']], test: (s, v) => (measured(s) > 0) === (v === 'yes')}] : [])],
      sorts: [['order', 'In order'], ['utility', 'Highest utility first', (a, b) => (b.set.utility ?? -1) - (a.set.utility ?? -1)]]}).el;
  }

  function proposalCard(prop, reload) {
    const settings = prop.group ? ` · pulse ${prop.group.pulse_width} ns · interval ${prop.group.line_interval} mm · passes ${prop.group.passes}` : '';
    const [statusText, statusKind] = STATUS[prop.status] || [prop.status, ''];
    const setup = prop.setup ? `${prop.setup.device} · ${App.lensLabel(prop.setup.lens)}` : null;
    const stock = !prop.stock ? null : prop.stock.material ? stockName(prop.stock.material)
      : 'all stocks measured with these settings: ' + (prop.stock.measured.map((s) => `${stockName(s)} (${s.sets})`).join(', ') || 'none yet');
    const history = prop.status_history.length ? h('details', {class: 'small'}, h('summary', {}, 'Status history'), table(['When', 'Status', 'Basis'],
      prop.status_history.map((e) => [when(e.at), (STATUS[e.to_status] || [e.to_status])[0], h('span', {}, I18N.tr(e.reason), e.note ? ` — «${e.note}»` : null,
        e.finding_id ? h('span', {}, ' · ', link('/findings?finding=' + e.finding_id, 'finding #' + e.finding_id)) : null)]), '', true)) : null;
    const actions = prop.status === 'proposed' ? h('div', {class: 'row'}, btn('Accept and create plates', () => plateDialog(prop, reload), 'primary'),
      btn('Reject', () => rejectDialog(prop, reload), 'danger')) : null;
    return h('div', {class: 'card stack'},
      h('h3', {}, `Proposal #${prop.id} · seed ${prop.seed} · sets ${prop.parameters.length}${settings}`, pill(statusText, statusKind)),
      (prop.questions || []).length ? h('div', {}, h('h4', {}, 'Question'), h('ul', {}, prop.questions.map((q) => h('li', {}, I18N.tr(q))))) : null,
      (prop.worth || []).length ? h('div', {}, h('h4', {}, 'Value of the result'), h('ul', {}, prop.worth.map((w) => h('li', {}, I18N.tr(w))))) : null,
      facts([['Task', prop.task ? TASK[prop.task] || prop.task : null], ['Laser and lens', setup], ['Titanium', stock],
        ['Based on findings', prop.origins.length ? h('span', {}, prop.origins.map((o) => link('/findings?finding=' + o.finding_id, '#' + o.finding_id))) : null]]),
      h('p', {class: 'muted small'}, `Database state signature: ${prop.base_signature}. The same data and seed produce the same proposal.`),
      h('h4', {}, `Parameter sets · ${prop.parameters.length}`), setsList(prop),
      actions, platesBlock(prop), explanationBlock(prop, reload), history);
  }

  /** Only supported pulse steps are offered; 200 ns is the default only when supported. */
  function pulseSelect(device, wanted) {
    const steps = (device?.passport?.pulse_steps || []).map((x) => +x.pulse_width_ns);
    const value = steps.includes(+wanted) ? +wanted : steps.includes(200) ? 200 : null;
    return h('select', {'aria-label': 'Pulse width'}, h('option', {value: '', selected: value == null}, 'select'),
      steps.map((w) => h('option', {value: w, selected: w === value}, w + ' ns')));
  }

  App.register({id: 'designer', async render(ctx) {
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Add a laser first'), link('/devices', 'Lasers'));
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens, onChange: () => { location.hash = '#/designer?' + pick.route(); }});
    const [map, props] = await Promise.all([get('/color-model?' + pick.query()), get('/designer/proposals?' + pick.query())]);
    const reload = () => App.render({preserveScroll: true});
    const proposeForm = Forms.create();
    const Q = Forms.QUANTITIES;
    const seed = Forms.numberInput(Q.seed, {value: 1729}), size = Forms.numberInput(Q.proposalSize, {value: 6});
    const chosen = props.find((p) => String(p.id) === ctx.query.proposal) || props[0] || null;
    const prop = chosen ? await get('/designer/proposals/' + chosen.id) : null;      // with its plates, photographs and results
    const group = prop?.group || {};
    // one stock record is chosen by a search among the records used last and the whole catalogue a page at a time; none means all measured stocks (ux-growing-collections-p0, REQ-001)
    const stock = MaterialPicker.create({value: prop?.stock?.material_id, allowEmpty: true, empty: 'all measured stocks', clearLabel: 'All stocks', name: 'Titanium'});
    const pulse = pulseSelect(pick.device(), group.pulse_width);
    const interval = Forms.numberInput(Q.lineInterval, {value: group.line_interval ?? 0.025});
    const passes = Forms.numberInput(Q.passes, {value: group.passes ?? 1});
    const pulseField = proposeForm.add('pulse', 'Pulse width', pulse, {required: true, help: 'only steps supported by this laser',
      read: () => (pulse.value === '' ? {ok: false, message: 'Select a pulse width supported by this laser'} : {ok: true, value: +pulse.value})});
    const intervalField = proposeForm.add('interval', 'Line interval', interval, {quantity: 'lineInterval', required: true});
    const passesField = proposeForm.add('passes', 'Layer passes', passes, {quantity: 'passes', required: true});
    const seedField = proposeForm.add('seed', 'Seed', seed, {quantity: 'seed', required: true});
    const sizeField = proposeForm.add('size', 'Number of sets', size, {quantity: 'proposalSize', required: true});
    // the latest measurement of a plate cell made for the target (REQ-006): delta E and the verdict by the saved tolerance
    const checked = (c) => (!c ? 'not yet measured' : !c.comparable ? 'measured without a chart: not comparable'
      : `ΔE ${num(c.delta_e, 1)}${c.within_tolerance == null ? ' · tolerance not set' : c.within_tolerance ? ' · within tolerance' : ' · outside tolerance'}`);
    const targets = map.targets.length ? table(['Color', 'Source plan', 'Proposal', 'Check'], map.targets.map((t) => [h('span', {}, swatch(t.lab), labText(t.lab)), link('/plans/' + t.source_plan_id, 'Source work'), t.proposal_id ? '#' + t.proposal_id : 'not yet addressed',
      t.checks?.length ? link('/analysis/' + t.checks[0].pair_id, checked(t.checks[0])) : checked(null)]))
      : h('p', {class: 'muted'}, 'No unreachable work colors. Gap-based selection is still available.');
    const propose = btn('Propose plate', async () => {
      const v = proposeForm.collect();
      if (!v) return;
      try { const r = await post('/designer/propose', {device_id: pick.deviceId(), lens_id: pick.lensId(), pulse_width: v.pulse, line_interval: v.interval,
        passes: v.passes, seed: v.seed, size: v.size, material_id: stock.value === '' ? null : +stock.value});
        location.hash = `#/designer?${pick.route()}&proposal=${r.id}`; App.render(); } catch (e) { proposeForm.fail(e); }
    }, 'primary');
    let body = null;
    if (prop) {
      const others = props.length > 1 ? h('div', {class: 'toolbar'}, field('Other proposals', h('select', {onChange: (e) => { location.hash = `#/designer?${pick.route()}&proposal=${e.target.value}`; }},
        props.map((p) => h('option', {value: p.id, selected: p.id === prop.id}, `#${p.id} · ${(STATUS[p.status] || [p.status])[0]} · ${when(p.created_at)}`))))) : null;
      body = h('div', {class: 'stack'}, others, ...prop.notes.map((n) => h('div', {class: 'alert warn'}, I18N.tr(n))),
        prop.unaddressed_targets.length ? h('div', {class: 'alert warn'}, 'Unaddressed targets: ' + prop.unaddressed_targets.join(', ')) : null,
        proposalCard(prop, reload));
    }
    return h('div', {class: 'stack'}, h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Experiment planner'), h('p', {class: 'sub'}, 'Choose what to measure next: gaps, uncertainty, instability, and targets.')),
      h('span', {class: 'spacer'})),
    h('div', {class: 'toolbar'}, h('div', {class: 'f-wrap'}, field('Laser', pick.laser)), h('div', {class: 'f-wrap'}, field('Lens', pick.lens)),
      link('/colors?' + pick.route(), 'Color model'), link('/findings', 'Findings'), link('/ingest', 'Add measurements')),
    h('div', {class: 'card stack'}, h('h3', {}, 'Targets from unreachable colors'), targets),
    h('div', {class: 'card stack'}, h('h3', {}, 'Work settings and search by power, frequency, and speed'),
      h('p', {class: 'muted small'}, 'Pulse width, line interval, and passes are fixed across the proposal. The model uses measurements with those settings for this laser and lens. Power, frequency, and speed stay within the laser datasheet.'),
      h('div', {class: 'grid g3'}, pulseField, intervalField, passesField,
        field('Titanium', stock, 'one stock: model uses only its measurements')),
      h('div', {class: 'toolbar'}, seedField, sizeField, propose,
        h('p', {class: 'toolbar-hint'}, 'The same seed and data produce the same proposal.')), proposeForm.error),
    map.samples.length ? null : h('div', {class: 'alert warn'}, 'Add measurements to analyze color space; sets are currently selected only from gaps.'), body);
  }});
})();
