/* Findings: evidence, uncertainty, operator decisions, and follow-up work. */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, post, put, toast, fail, num, labText, swatch, facts} = App;
  const KINDS = ['improvement', 'unstable', 'anomaly', 'gap', 'hypothesis'];
  const KIND = {improvement: 'Improvements', unstable: 'Instability', anomaly: 'Anomalies', gap: 'Gaps', hypothesis: 'AI hypotheses'};
  const KIND_ONE = {improvement: 'Improvement', unstable: 'Unstable', anomaly: 'Anomaly', gap: 'Gap', hypothesis: 'AI hypothesis'};
  const BASIS = {measured: ['Measured', 'ok'], exploratory: ['Exploratory anomaly, not a conclusion', 'warn'],
    hypothesis: ['AI hypothesis, not a measurement', 'bad']};
  const TRIGGER = {acceptance: 'after photo acceptance', manual: 'manually', schedule: 'on schedule', recheck: 'after rechecking all work',
    operator: 'after an operator decision'};
  const STATES = [['attention', 'Needs attention'], ['acknowledged', 'Acknowledged'], ['hidden', 'Hidden']];
  const SORTS = [['important', 'Most important first'], ['newest', 'Newest first'], ['delta', 'Largest ΔE'], ['setup', 'By laser and titanium']];
  const STAGE = {measured: 'measured', candidate: 'candidate', repeated: 'repeated', validated: 'validated', production: 'production'};
  const when = (iso) => (iso ? new Date(iso).toLocaleString('en-US', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit'}) : '—');
  const taskName = (t) => (t ? Tasks.name(t) : 'task not defined');     // tasks use a shared vocabulary (REQ-020, tasks.js)
  let goalNames = {};                     // management goals (/application-goals): AI research purpose
  const stockName = (s) => (s ? [s.name, s.grade, s.batch].filter(Boolean).join(' · ') || 'unnamed titanium' : 'titanium not specified');
  const setupName = (c) => `${c.device || 'laser #' + c.device_id} · ${App.lensLabel(c.lens)}`;
  const settings = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} kHz · ${num(p.speed, 0)} mm/s · ${num(p.pulse_width, 0)} ns · interval ${num(p.line_interval, 4)} mm · ${p.passes ?? '—'} passes`;
  /** Why the server recommends this step (the ids are those of ``findings.RECOMMENDATION_RULES``). */
  const WHY = {
    recheck_running: 'All work is being rechecked: photos cannot be remeasured and calculation decisions cannot be made now. Review the finding’s evidence.',
    measurement_anomaly: 'Remeasure the photo first: if the measurement is wrong, the new one will correct it. Investigate the cause before excluding it or recalculating the recipe.',
    corrective_choice_ambiguous: 'The correction depends on the cause, which is not yet clear. First review the supporting photos and knowledge records.',
    experiment_for_gap: 'Data is missing: the laboratory will propose an experiment to close the gap.',
    good_news: 'Nothing needs correcting: mark acknowledged after reading.',
    evidence_to_read: 'This finding proposes no correction; review its evidence.',
    nothing_to_do: 'No action is proposed: mark acknowledged after reading.',
    already_handled: 'You already acknowledged this finding; it returns to Needs attention when new data arrives.'};
  const designerRoute = (deviceId, lensId, proposalId) => `/designer?device=${deviceId}&lens=${App.lensParam(lensId)}${proposalId ? '&proposal=' + proposalId : ''}`;

  function samples(s) {
    if (!s) return '—';
    const parts = [];
    if (s.recipes != null) parts.push(`recipes: ${s.recipes}`);
    if (s.independent_engravings != null) parts.push(`independent engravings: ${s.independent_engravings}`);
    if (s.photographs != null) parts.push(`photos: ${s.photographs}`);
    if (s.observations != null) parts.push(`observations: ${s.observations}`);
    return parts.join(' · ') || '—';
  }

  function uncertainty(f) {
    const u = f.uncertainty || {};
    if (f.basis === 'hypothesis') return `not measured; AI-assigned confidence: ${u.ai_confidence === 'candidate' ? 'candidate' : 'hypothesis'}`;
    if (f.subkind === 'coverage') return 'no data';
    if (u.expected_delta_e != null) {
      return `expected ΔE error ${num(u.expected_delta_e)} · variance ${num(u.variance)} ΔE² · confidence ${num(u.confidence)}`
        + (u.rig_mean_delta_e != null ? ` · rig repeatability ΔE ${num(u.rig_mean_delta_e)}` : '');
    }
    if (u.delta_e != null) return `nearest measurement ΔE ${num(u.delta_e, 1)} · ` + (u.tolerance != null ? `tolerance ${u.tolerance}` : 'no tolerance saved');
    if (f.subkind === 'target_missing') return 'not assessed: no comparable target measurements yet';
    return 'not assessed: fewer than two independent engravings';
  }

  /** What the finding compares, by type. */
  function compares(f) {
    const c = f.compares || {};
    switch (f.subkind) {
      case 'error_reduced': return `Against run #${c.previous_run_id}: expected ΔE error ${num(c.before.expected_delta_e)} → ${num(c.after.expected_delta_e)}, `
        + `independent engravings ${c.before.independent_engravings} → ${c.after.independent_engravings}`;
      case 'validated': return `Stage “${STAGE[c.stage] || c.stage}”${c.since ? ' since ' + when(c.since) : ''}; criteria: repeats ${c.repeat_threshold ?? '—'}, `
        + `ΔE tolerance ${c.delta_tolerance ?? '—'}, variance threshold ${c.variance_threshold ?? '—'}`;
      case 'variance': return `Repeat variance ${num(c.variance)} ΔE² against saved threshold ${c.variance_threshold}`;
      case 'questioned': {
        const doubt = c.doubt_observation_ids || [];
        const stage = `Stage “${STAGE[c.stage] || c.stage}”`;
        // a few observations are named in the line; many are a count with a list of links (ux-growing-collections-p0, REQ-002)
        return doubt.length > SourceRefs.SHORT ? [stage, SourceRefs.observations(doubt, {label: 'Observations that raised doubt'})]
          : `${stage}; observations that raised doubt: ${doubt.join(', ') || '—'}`;
      }
      case 'observation': return [h('span', {}, swatch(c.observation_lab), ' observation ', labText(c.observation_lab)), ' versus ',
        h('span', {}, swatch(c.reference_lab), c.rule === 'tolerance' ? ' recipe mean ' : ' mean of other engravings ', labText(c.reference_lab)),
        ` · ΔE ${num(c.delta_e, 1)} · ` + (c.rule === 'tolerance' ? `tolerance ${c.tolerance}` : `3σ = ${num(3 * c.sd)} ΔE`)];
      case 'target_reached':
      case 'target_missing': return [h('span', {}, swatch(c.target_lab), ' target ', labText(c.target_lab)),
        c.closest_lab ? h('span', {}, ' · nearest measurement ', swatch(c.closest_lab), labText(c.closest_lab), ` · ΔE ${num(c.delta_e, 1)}`) : ' · no comparable measurements',
        c.tolerance != null ? ` · tolerance ${c.tolerance}` : ' · no tolerance saved'];
      case 'coverage': {
        const names = c.names || {stocks: {}, lenses: {}};
        const stocks = c.stocks_with_this_task.map((id) => stockName(names.stocks[id]));
        const lenses = c.lenses_with_this_task.map((id) => App.lensLabel(names.lenses[id]));
        return `Available on this titanium with this laser and lens: ${c.tasks_on_this_stock.map(taskName).join(', ') || 'none'}; this task is available `
          + (stocks.length ? `on stocks: ${stocks.join(', ')}` : 'on no other stock') + (lenses.length ? ` and with lenses: ${lenses.join(', ')}` : '');
      }
      case 'single_engraving': return (c.engravings_needed_for_validation == null ? 'The number of engravings needed for validation is unspecified: criteria have not been agreed'
        : `Additional independent engravings needed for validation: ${c.engravings_needed_for_validation}`) + ` · repeatable on a plate: ${c.repeatable_keys.length} of ${c.recipes.length}`;
      case 'insight': return `Saved by AI researcher ${when(c.saved_at)} · research purpose: ${goalNames[c.purpose] || c.purpose}`;
      default: return null;
    }
  }

  function evidence(f) {
    const e = f.evidence || {};
    const links = [];
    const pairs = e.pair_ids || [];
    // up to the old limits the numbers are links in the row; beyond them a count with a list of every one (ux-growing-collections-p0, REQ-002)
    if (pairs.length > 12) links.push(SourceRefs.photos(pairs, {label: 'Photos'}));
    else pairs.forEach((id) => links.push(link('/analysis/' + id, 'photo #' + id)));
    if (e.knowledge_id) links.push(link('/knowledge/' + e.knowledge_id, 'knowledge #' + e.knowledge_id));
    const known = e.knowledge_ids || [];
    if (known.length > 8) links.push(SourceRefs.refs(known, {label: 'Knowledge', href: (id) => '/knowledge/' + id}));
    else known.forEach((id) => links.push(link('/knowledge/' + id, 'knowledge #' + id)));
    if (e.target_id != null) links.push(link(designerRoute(f.device_id, f.lens_id), 'target #' + e.target_id));
    if (e.plan_id) links.push(link('/plans/' + e.plan_id, 'target source work'));
    if (e.proposal_id) links.push(link(designerRoute(f.device_id, f.lens_id, e.proposal_id), 'proposal #' + e.proposal_id));
    if (e.session_id) links.push(link('/research/' + e.session_id, 'research #' + e.session_id));
    const obs = e.observation_ids || [];
    return h('div', {class: 'row small fd-evidence'}, h('span', {class: 'muted'}, 'Evidence:'),
      links.length ? links : h('span', {class: 'muted'}, 'no accepted records'),
      obs.length > 8 ? SourceRefs.observations(obs, {label: 'Observations'}) : null,
      obs.length && obs.length <= 8 ? h('span', {class: 'muted'}, `observations #${obs.join(', ')}`) : null);
  }

  /** The same finding across runs; consecutive identical versions are grouped. */
  function historyBlock(f) {
    const body = h('div', {class: 'small'}, h('p', {class: 'muted'}, 'Loading…'));
    const details = h('details', {}, h('summary', {}, 'Finding history across runs'), body);
    details.addEventListener('toggle', async () => {
      if (!details.open || details.dataset.loaded) return;
      details.dataset.loaded = '1';
      try {
        const rows = [];
        for (const x of await get(`/analysis/findings/${f.id}/history`)) {
          const last = rows[rows.length - 1];
          if (last && last.kind === x.kind && last.statement === x.statement) last.runs.push(x);
          else rows.push({kind: x.kind, statement: x.statement, runs: [x]});
        }
        App.fill(body, App.table(['Runs', 'Type', 'Finding'], rows.map((r) => {
          const first = r.runs[r.runs.length - 1], last = r.runs[0];
          return [r.runs.length === 1 ? `№ ${last.run_id} · ${when(last.run_at)}` : `№ ${first.run_id}–${last.run_id} · ${when(first.run_at)} — ${when(last.run_at)} (${r.runs.length})`,
            KIND_ONE[r.kind] || r.kind, I18N.tr(r.statement)];
        }), 'No history', true));
      } catch (e) { App.fill(body, h('div', {class: 'alert bad'}, e.message)); }
    });
    return details;
  }

  function proposeButton(f, cls = 'primary btn-small') {
    if (f.kind !== 'gap' || !f.proposable) return null;
    return btn('Propose experiment', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const p = await post(`/analysis/findings/${f.id}/proposal`, {});
        toast(`Proposal #${p.id} is ready`, 'ok');
        App.go(designerRoute(p.device_id, p.lens_id, p.id));
      } catch (e) { fail(e); self.disabled = false; }
    }, cls);
  }

  function findingCard(f) {
    const [basis, basisKind] = BASIS[f.basis] || [f.basis, ''];
    const c = f.context || {};
    const recipe = f.recipe && f.recipe.lab ? h('p', {class: 'small'}, swatch(f.recipe.lab), ' ', labText(f.recipe.lab), ' · ', settings(f.recipe.parameters)) : null;
    return h('article', {class: 'stack finding'},
      h('div', {class: 'row'}, pill(KIND_ONE[f.kind] || f.kind), pill(basis, basisKind), f.new ? pill('new in this run', 'ok') : null,
        h('span', {class: 'spacer'}), f.recommendation && f.recommendation.action === 'propose_experiment' ? null : proposeButton(f)),   // the recommended step already holds it
      h('p', {}, h('strong', {}, I18N.tr(f.statement))),
      recipe,
      facts([['Laser and lens', setupName(c)], ['Titanium', stockName(c.stock)], ['Task', taskName(f.task)], ['Samples', samples(f.samples)],
        ['Uncertainty', uncertainty(f)], ['Compares', compares(f)]]),
      (f.limitations || []).length ? h('ul', {class: 'small muted'}, f.limitations.map((l) => h('li', {}, I18N.tr(l)))) : null);
  }

  // -- the operator's marks (REQ-003): «Acknowledge», «Hide» / «Restore», «Pin», a note; ``done`` reads the findings again
  const mark = (f, action, note) => post(`/analysis/findings/${f.id}/mark`, note === undefined ? {action} : {action, note});
  const DONE = {acknowledge: 'Acknowledged: the finding returns to Needs attention when new data arrives.',
    hide: 'Hidden until new data arrives; find it under Hidden.', reopen: 'The finding needs attention again.'};
  function markButtons(f, done, openNote) {
    const advised = f.recommendation && f.recommendation.action === 'acknowledge' && f.state === 'attention';
    const act = (action, text) => btn(text, async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await mark(f, action); if (DONE[action]) toast(DONE[action], 'ok'); await done(); }
      catch (e) { fail(e); self.disabled = false; }
    }, action === 'acknowledge' && advised ? 'primary btn-small fd-recommended' : 'btn-small');
    return [f.state === 'attention' ? act('acknowledge', 'Acknowledge') : act('reopen', 'Restore'),
      f.state !== 'hidden' ? act('hide', 'Hide') : null,
      btn('Note', () => openNote(), 'btn-small'),
      act(f.mark.pinned ? 'unpin' : 'pin', f.mark.pinned ? 'Unpin' : 'Pin')];
  }

  function markBlock(f, done) {
    const m = f.mark;
    const was = m.status === 'hidden' ? 'hidden' : 'acknowledged';
    const status = m.changed ? `Previously ${was} ${when(m.status_at)}; new data has arrived and the finding needs attention again.`
      : m.status ? `${m.status === 'hidden' ? 'Hidden' : 'Acknowledged'} ${when(m.status_at)}: returns when new data arrives.` : null;
    const form = Forms.create();
    const note = h('textarea', {rows: '2', placeholder: 'What was done, what to check…'});
    note.value = m.note || '';
    // the server keeps the first 2000 characters of a note; a longer one is refused here with its length rather than cut short without a word
    const noteField = form.add('note', 'Operator note', note, {raw: true, maxLength: 2000});
    const save = btn('Save note', async (ev) => {
      const self = ev.currentTarget;
      const v = form.collect();
      if (!v) return;
      self.disabled = true;
      try { await mark(f, 'note', v.note); toast('Note saved', 'ok'); await done(); }
      catch (e) { form.fail(e); self.disabled = false; }
    }, 'btn-small');
    return h('div', {class: 'stack fd-mark'}, status ? h('p', {class: 'small muted'}, status) : null,
      h('div', {class: 'toolbar'}, noteField, save), form.error);
  }

  // -- what can be done about a finding (act-on-findings REQ-001..REQ-004) ---------------------------------------------------
  const REMEDY = {
    exclude_measurement: ['Exclude measurement', 'This layer of this photo will be excluded from the recipe, color map, palette, and works. '
      + 'The photo and its other layers remain; Restore reverses the decision.'],
    remeasure: ['Remeasure photo', 'Measure the photo again using the current method (about half a minute). If the new measurement '
      + 'does not complete, the previous one remains.'],
    count_from_latest: ['Count from latest engraving', 'Use the latest engraving for the recipe color. Older engravings remain in history but are excluded; '
      + 'later engravings count as usual.'],
    confirm_questioned: ['Confirm record', 'Remove the questioned flag from the knowledge record; its stage stays the same.'],
  };
  const DECIDED = {exclude_measurement: 'measurement excluded from calculation', count_from_latest: 'recipe counts from latest engraving'};
  const layerName = (name, index) => (name ? `«${I18N.name(name)}»` : `№ ${index}`);
  const longPhotos = (e) => e.pair_ids.length > SourceRefs.SHORT;
  const engravingText = (e) => `${e.title || 'engraving'} · ${when(e.when)} · ` + (longPhotos(e) ? `photos: ${e.pair_ids.length}` : `photo #${e.pair_ids.join(', ')}`);
  /** The photographs of an engraving beyond a few: a count with a list of links under its line. */
  const engravingPhotos = (e) => (longPhotos(e) ? SourceRefs.photos(e.pair_ids, {label: 'Photos'}) : null);

  /** The recipe's colour before and after a decision, as the knowledge will derive it. */
  function colourChange(p) {
    const side = (c) => (c ? h('span', {}, swatch(c.lab), labText(c.lab), ` · engravings: ${c.engravings}`)
      : h('span', {class: 'muted'}, 'no measurements will remain in the recipe'));
    return h('div', {class: 'stack small fd-change'}, h('strong', {}, 'Recipe color'), h('div', {}, 'now: ', side(p.before)),
      h('div', {}, 'after: ', side(p.after)), p.delta_e != null ? h('div', {class: 'muted'}, `ΔE shift ${num(p.delta_e, 1)}`) : null);
  }

  /** What leaves the calculation: one layer of one photograph, or the older engravings of a recipe. */
  function leaving(p) {
    if (p.action === 'exclude_measurement') {
      const o = p.observation;
      return h('p', {}, 'Will be excluded: ', link('/analysis/' + o.pair_id, `photo #${o.pair_id}`), `, layer ${layerName(o.layer_name, o.layer_index)} `,
        h('span', {}, swatch(o.lab), labText(o.lab)));
    }
    return h('div', {class: 'stack small'}, h('div', {}, 'Will remain: ', swatch(p.kept.lab), ' ', engravingText(p.kept), engravingPhotos(p.kept)),
      h('div', {}, `Will be excluded (${p.older.length}):`),
      h('ul', {}, p.older.slice(0, 6).map((e) => h('li', {}, swatch(e.lab), ' ', engravingText(e), engravingPhotos(e)))),
      p.older.length > 6 ? h('div', {class: 'muted'}, `and another ${p.older.length - 6}`) : null);
  }

  /** «Restore»: the measurements of a decision count again; the screen is drawn again with the new run. */
  async function revoke(id) {
    try {
      const r = await post(`/exclusions/${id}/revoke`, {});
      toast('Included again' + (r.run_id ? ` · run #${r.run_id}` : ''), 'ok');
      App.render({preserveScroll: true});
    } catch (e) { fail(e); }
  }

  /** A decision: what it changes first (REQ-004), a note, then the decision and the screen with the new run and «Restore». */
  async function decide(f, action) {
    const preview = await post(`/analysis/findings/${f.id}/remedy`, {action});
    const form = Forms.create();
    const note = form.add('note', 'Note', h('textarea', {rows: '2', placeholder: 'Why (optional)'}), {raw: true, maxLength: 2000});
    App.modal(REMEDY[action][0] + '?', h('div', {class: 'stack fd-remedy-preview'}, leaving(preview), colourChange(preview),
      h('p', {class: 'muted small'}, 'Measurements themselves do not change: the decision is stored separately and Restore reverses it. After the decision, '
        + 'knowledge, findings, and works are recalculated.'), note, form.error),
    [{label: 'Cancel', run: (m) => m.close()},
      {label: REMEDY[action][0], cls: 'primary', run: async (m) => {
        const v = form.collect();
        if (!v) return;
        let r;
        try { r = await post(`/analysis/findings/${f.id}/remedy`, {action, note: v.note, confirm: true}); } catch (e) { form.fail(e); return; }
        m.close();
        toast([`Done · ${DECIDED[action]}${r.run_id ? ` · run #${r.run_id}` : ''} `, btn('Restore', () => revoke(r.exclusion.id), 'btn-small')], 'ok');
        App.render({preserveScroll: true});
      }}]);
  }

  /** «Remeasure photo» from the finding (REQ-003): busy while it measures, then every layer's colour before and after (the finding's layer
      first), or why the old measurement was kept; the screen is drawn again when the result is closed. */
  const measuring = new Set();                       // photographs being measured again: a second click on any button for one waits for the first
  async function remeasure(f, pairId, control) {
    if (measuring.has(pairId)) return;
    measuring.add(pairId);
    control.disabled = true;
    control.textContent = 'Remeasuring… (about half a minute)';
    let out;
    try { out = await post(`/pairs/${pairId}/remeasure`); }
    catch (e) { fail(e); control.disabled = false; control.textContent = REMEDY.remeasure[0]; return; }
    finally { measuring.delete(pairId); }
    const own = f.kind === 'anomaly' ? Number(String(f.key).split(':')[3]) : null;
    const body = out.status !== 'replaced' ? h('p', {}, 'Previous measurement retained: ' + I18N.tr(out.reason || ''))
      : h('div', {class: 'stack'}, h('p', {}, `Photo #${pairId} remeasured; new measurement: `, link('/analysis/' + out.replaced_by, `photo #${out.replaced_by}`), '.'),
        App.list({items: out.layers, key: (l) => String(l.layer_index), className: 'fd-remeasured',
          row: (l) => [l.layer_index === own ? pill('this finding', 'warn') : null, h('span', {class: 'lst-text'}, `Layer ${layerName(l.name, l.layer_index)}`),
            l.before ? swatch(l.before) : null, '→', l.after ? swatch(l.after) : null,
            h('span', {class: 'small'}, l.delta_e != null ? `ΔE ${num(l.delta_e, 1)}` : 'no pair')],
          details: (l) => facts([['Before', l.before ? labText(l.before) : '—'], ['After', l.after ? labText(l.after) : '—']]),
          sorts: [['delta', 'Largest shift', (a, b) => (b.layer_index === own) - (a.layer_index === own) || (b.delta_e ?? -1) - (a.delta_e ?? -1)],
            ['order', 'Layer order', (a, b) => a.layer_index - b.layer_index]]}).el);
    App.modal(out.status === 'replaced' ? 'Photo remeasured' : 'Photo not remeasured', body, [{label: 'Close', run: (m) => m.close()}],
      () => App.render({preserveScroll: true}));
  }

  /** «Confirm record» of a questioned knowledge entry, then a new run so the finding goes. */
  function confirmEntry(kid) {
    App.modal('Confirm record?', h('p', {}, `Knowledge record #${kid} will no longer be flagged as questioned; its stage does not change. `, link('/knowledge/' + kid, 'Open record')),
      [{label: 'Cancel', run: (m) => m.close()},
        {label: 'Confirm', cls: 'primary', run: async (m) => {
          await post(`/knowledge/${kid}/confirm-questioned`, {});
          const r = await post('/analysis/runs');
          m.close();
          toast(`Record confirmed · run #${r.id}`, 'ok');
          App.render({preserveScroll: true});
        }}]);
  }

  /** The button of one remedy the finding offers (the same flows as ever: the preview and the confirmation of a decision, the measuring again). */
  function remedyButton(f, r, cls = 'btn-small') {
    return btn(REMEDY[r.action][0], async (ev) => {
      const self = ev.currentTarget;
      if (r.action === 'remeasure') { await remeasure(f, r.pair_id, self); return; }
      self.disabled = true;
      try { if (r.action === 'confirm_questioned') confirmEntry(r.knowledge_id); else await decide(f, r.action); }
      catch (e) { fail(e); } finally { self.disabled = false; }
    }, cls);
  }

  /** «Other actions»: every remedy the finding offers except the one recommended, each with a line on what it does, behind a fold;
      nothing for a finding with none (an earlier run offers none). */
  function otherActions(f) {
    const advised = f.recommendation && f.recommendation.action === 'remeasure' ? 'remeasure' : null;
    const offered = (f.remedies || []).filter((r) => REMEDY[r.action] && r.action !== advised);
    if (!offered.length) return null;
    return h('details', {class: 'fd-more-actions'}, h('summary', {}, `Other actions (${offered.length})`),
      h('div', {class: 'stack fd-remedies'}, offered.map((r) => h('div', {class: 'fd-remedy'}, remedyButton(f, r), h('span', {class: 'muted small'}, REMEDY[r.action][1])))));
  }

  /** The one recommended step as a button: measure the photograph again, open the evidence (the row opens under its own line), propose an
      experiment; «Acknowledge» is the mark button itself, drawn as the recommended one. ``open`` opens the evidence where the finding is shown. */
  function nextButton(f, open, cls = 'primary btn-small fd-recommended') {
    const r = f.recommendation;
    if (!r) return null;
    if (r.action === 'remeasure') {
      return btn(REMEDY.remeasure[0], async (ev) => {
        const self = ev.currentTarget;
        await remeasure(f, r.pair_id, self);
      }, cls);
    }
    if (r.action === 'open_evidence') return btn('Open evidence', () => open(f), cls);
    if (r.action === 'propose_experiment') return proposeButton(f, cls);
    return null;
  }

  /** «Next step»: the recommended step, why, and — when the step is not «Acknowledge» — nothing else; the rest is under «Other actions». */
  function nextBlock(f, open) {
    const r = f.recommendation;
    if (!r) return null;
    const button = nextButton(f, open, 'primary btn-small');
    const why = WHY[r.rule];
    return h('div', {class: 'fd-remedies fd-next', 'data-action': r.action},
      h('h4', {}, 'Next step'), h('div', {class: 'fd-remedy'}, button, h('span', {class: 'muted small fd-next-why'}, why || '')));
  }

  /** What an opened finding shows, in the order of a decision: the recommended step, the evidence it rests on, the other actions, the
      operator's mark and note, then the finding itself with its figures; its history by calculation is a fold. */
  /** The words the finding uses without saying what they are (ux-save-feedback-p0, REQ-003): the basis it rests on, and — when it rests on them — the photo
      and engraving pair, the knowledge entry and its stage, each explained through what the person is doing, the technical number inside. */
  function termsBlock(f) {
    const e = f.evidence || {};
    const pairs = e.pair_ids || [], known = [e.knowledge_id, ...(e.knowledge_ids || [])].filter((id) => id != null);
    return h('div', {class: 'stack kn-terms'}, Terms.note('basis'), pairs.length ? Terms.note('pair', pairs.length === 1 ? pairs[0] : null) : null,
      known.length ? Terms.note('knowledge', known.length === 1 ? known[0] : null) : null, known.length ? Terms.note('stage') : null);
  }
  function findingDetails(f, done, open) {
    return [nextBlock(f, open), evidence(f), termsBlock(f), otherActions(f), markBlock(f, done), findingCard(f), historyBlock(f)];
  }

  /** «Excluded by operator N» (REQ-005): the decisions in force as a short list, each with «Restore»; nothing when there is none. */
  function exclusionsBlock(x) {
    if (!x || !x.active) return null;
    const what = (e) => (e.kind === 'measurement'
      ? `Measurement: photo #${e.pair_id ?? e.original_pair_id}, layer ${layerName((e.observation || {}).layer_name, e.layer_index)}`
      : `Recipe ${settings(e.settings || {})} — from latest engraving${e.kept && e.kept.title ? ` «${e.kept.title}»` : ''}`);
    const shown = (e) => (e.kind === 'measurement' ? (e.observation || {}).lab : (e.after || {}).lab);
    const list = App.list({items: x.exclusions, key: (e) => String(e.id), search: (e) => `${what(e)} ${e.note || ''}`,
      row: (e) => [shown(e) ? swatch(shown(e)) : null, h('span', {class: 'lst-text', title: what(e)}, what(e)), h('span', {class: 'muted small'}, when(e.created_at)),
        e.note ? h('span', {class: 'muted small fd-note', title: e.note}, '✎ ' + e.note) : null],
      details: (e) => h('div', {class: 'stack small'}, facts([['Excluded', what(e)],
        ['Observations excluded', String(e.observations_out ?? '—')],
        ['Recipe color at decision', [e.before ? h('span', {}, swatch(e.before.lab), ' ', labText(e.before.lab)) : '—', ' → ',
          e.after ? h('span', {}, swatch(e.after.lab), ' ', labText(e.after.lab)) : 'no measurements remain']],
        ['Decision', when(e.created_at)], ['Note', e.note || '—']]),
        e.kind === 'measurement' && e.pair_id ? h('p', {}, link('/analysis/' + e.pair_id, 'Open photo')) : null),
      actions: (e) => [btn('Restore', () => revoke(e.id), 'btn-small')],
      filters: [{key: 'kind', label: 'Type', options: [['measurement', 'Measurements'], ['older_engravings', 'Recipes']], test: (e, v) => e.kind === v}],
      sorts: [['newest', 'Newest first', (a, b) => b.id - a.id]], className: 'fd-excluded-list'});
    return h('details', {class: 'card fd-fold fd-excluded'}, h('summary', {}, `Excluded by operator: ${x.active}`), list.el);
  }

  /** One line of the list: pinned, kind, the statement, laser and titanium, ΔE, new or changed, its mark, a note. */
  function row(f) {
    const c = f.context || {};
    return [f.mark.pinned ? h('span', {title: 'Pinned to top', 'aria-label': 'Pinned to top'}, '📌') : null,
      h('span', {class: 'fd-kind fd-' + f.kind}, KIND_ONE[f.kind] || f.kind),
      h('span', {class: 'lst-text', title: I18N.tr(f.statement)}, I18N.tr(f.statement)),
      h('span', {class: 'muted small fd-where', title: `${setupName(c)} · ${stockName(c.stock)}${f.task ? ' · ' + taskName(f.task) : ''}`},
        `${c.device || 'laser #' + f.device_id} · ${stockName(c.stock)}${f.task ? ' · ' + taskName(f.task) : ''}`),
      f.deviation != null ? h('span', {class: 'small'}, `ΔE ${num(f.deviation, 1)}`) : null,
      f.mark.changed ? pill('changed', 'warn') : f.new ? pill('new', 'ok') : null,
      f.state === 'hidden' ? pill('hidden') : f.state === 'acknowledged' ? pill('acknowledged') : null,
      f.mark.note ? h('span', {class: 'muted small fd-note', title: f.mark.note}, '✎ ' + f.mark.note) : null];
  }

  function rulesAlerts(run) {
    const MISSING = {variance_threshold: 'variance threshold is missing; instability is not assessed', delta_tolerance: 'ΔE tolerance is missing; anomalies use three standard deviations and target-color achievement is not assessed'};
    return (run.inputs.unset_rules || []).map((u) => h('div', {class: 'alert warn small'}, `${setupName(u)}: not saved: ${u.missing.map((m) => MISSING[m]).join('; ')}. `,
      link('/setup', 'Assessment rules')));
  }

  function scheduleBlock(schedule) {
    const form = Forms.create();
    const hours = form.add('hours', 'Recalculate every (0 disables)', Forms.numberInput(Forms.QUANTITIES.analysisInterval, {value: schedule.interval_hours}),
      {quantity: 'analysisInterval', required: true});
    const state = schedule.interval_hours > 0
      ? `Enabled: every ${schedule.interval_hours} hours. Next run: ${when(schedule.next_due_at)}${schedule.running ? '' : ' (starts after the application restarts)'}.`
      : 'Disabled: findings are recalculated after each photo acceptance and on request.';
    return h('div', {class: 'stack'}, h('h4', {}, 'Scheduled recalculation'), h('p', {class: 'muted small'}, state),
      h('div', {class: 'toolbar'}, hours,
        btn('Save schedule', async (ev) => {
          const self = ev.currentTarget;
          const v = form.collect();
          if (!v) return;
          self.disabled = true;
          try { await put('/analysis/schedule', {interval_hours: v.hours}); toast('Schedule saved', 'ok'); App.render({preserveScroll: true}); }
          catch (e) { form.fail(e); self.disabled = false; }
        })), form.error);
  }

  // -- «Recheck all work» (REQ-004, DEC-089) ----------------------------------------------------------------------
  const RECHECK_POLL_MS = 1000;
  const RECHECK_PHASE = {backup: 'Backing up the workshop…', analysis: 'Recalculating findings…'};
  const RECHECK_END = {done: 'Recheck completed', cancelled: 'Recheck stopped', failed: 'Recheck failed',
    interrupted: 'Recheck interrupted: the application was closed'};
  const PHOTO = {replaced: ['replaced', 'ok'], kept: ['previous retained', 'warn'], failed: ['error', 'bad']};
  const CHANGE = {appeared: ['appeared', 'ok'], gone: ['gone', ''], changed: ['changed', 'warn']};
  const mb = (bytes) => (bytes == null ? '—' : bytes >= 1024 * 1024 * 1024 ? `${(bytes / 1024 / 1024 / 1024).toFixed(1).replace('.', ',')} GB`
    : `${(bytes / 1024 / 1024).toFixed(bytes < 10 * 1024 * 1024 ? 1 : 0).replace('.', ',')} MB`);
  const duration = (s) => (s < 90 ? `${Math.max(1, Math.round(s))} s` : `${Math.round(s / 60)} min`);

  /** Ask first: how many photographs, about how long, where the backup goes and whether it fits; then start and follow. */
  function recheckButton(box) {
    return btn('Recheck all work', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const p = await get('/recheck/preview');
        if (p.running) { followRecheck(box, await get('/recheck/latest')); return; }
        const short = p.free_bytes != null && p.free_bytes < p.backup_bytes;
        const body = !p.photos ? h('p', {}, 'No accepted photos: nothing to recheck.') : h('div', {class: 'stack'},
          h('p', {}, `All accepted photos (${p.photos}) will be remeasured using the current method, and findings recalculated once at the end. `
            + `Estimated time: ${duration(p.estimate_s)}.`),
          h('p', {}, `First, a full workshop backup is made in ${p.backup_dir} (${mb(p.backup_bytes)}, ${mb(p.free_bytes)} free): `
            + 'the new measurement replaces the old one and its files; the previous version can only be restored from this backup.'),
          h('p', {class: 'muted small'}, 'If a photo cannot be completely remeasured, the old measurement remains. While the recheck runs, photos cannot be '
            + 'accepted, remeasured, or deleted; the recheck can be stopped between photos.'),
          short ? h('div', {class: 'alert bad'}, 'There is not enough space for the backup: free space or choose another backup folder in Workshop.') : null);
        App.modal('Recheck all work?', body, !p.photos || short ? [{label: 'Close', run: (m) => m.close()}]
          : [{label: 'Cancel', run: (m) => m.close()},
            {label: 'Recheck', cls: 'primary', run: async (m) => { const started = await post('/recheck', {}); m.close(); followRecheck(box, started); }}]);
      } catch (e) { fail(e); } finally { self.disabled = false; }
    }, 'btn-small');
  }

  /** A re-check running: its phase, «k of N» with the photograph being measured and the time left, a bar and «Stop»; polled every
      second while the screen shows it (the re-check goes on when the screen is left); at the end the screen is drawn again with the report. */
  function followRecheck(box, r) {
    const fillBar = h('div', {class: 'lab-bar-fill'});
    const meter = h('div', {role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': String(r.total), 'aria-label': 'Recheck all work'},
      h('div', {class: 'lab-bar'}, fillBar));
    const text = h('span', {class: 'small'});
    const stopButton = btn('Stop', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await post(`/recheck/${r.id}/stop`, {}); toast('The recheck will stop after the photo currently being measured', 'ok'); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    App.fill(box, h('div', {class: 'row'}, h('strong', {class: 'small'}, 'Recheck all work'), text, h('span', {class: 'spacer'}), stopButton), meter);
    const show = () => {
      const c = r.current;
      const left = r.done && r.total > r.done ? ` · remaining ≈ ${duration(r.elapsed_s / r.done * (r.total - r.done))}` : '';
      text.textContent = r.phase === 'remeasure'
        ? `Remeasuring photo ${Math.min(r.done + 1, r.total)} of ${r.total}` + (c ? ` · ${c.title || c.photo_name} (photo #${c.pair_id})` : '') + left
        : RECHECK_PHASE[r.phase] || r.phase;
      const percent = r.total ? Math.round(r.done / r.total * 100) : 0;
      fillBar.setAttribute('style', `width:${percent}%`);
      meter.setAttribute('aria-valuenow', String(r.done));
    };
    const poll = async () => {
      if (!box.isConnected) return;
      try { r = await get(`/recheck/${r.id}`); } catch (e) { App.fill(box, h('div', {class: 'alert bad'}, e.message)); return; }
      if (r.status === 'running') { show(); setTimeout(poll, RECHECK_POLL_MS); return; }
      toast(RECHECK_END[r.status] || r.status, r.status === 'done' ? 'ok' : 'bad');
      App.render({preserveScroll: true});                         // the new run of conclusions and the report
    };
    show();
    setTimeout(poll, RECHECK_POLL_MS);
  }

  /** The report of the last re-check in a fold: the backup, the photographs (replaced, kept with the reason, failed; the largest colour
      change) and what changed in the findings, each as a short list. */
  function recheckReport(r, route) {
    const count = (s) => r.photos.filter((p) => p.status === s).length;
    const f = r.findings;
    const photos = App.list({items: r.photos, key: (p) => p.pair_id, search: (p) => `${p.title || ''} ${p.photo_name || ''} ${p.pair_id}`,
      row: (p) => [pill(...(PHOTO[p.status] || [p.status])), h('span', {class: 'lst-text'}, p.title || p.photo_name || `photo #${p.pair_id}`),
        h('span', {class: 'muted small'}, `photo #${p.pair_id}`), p.max_delta_e != null ? h('span', {class: 'small'}, `ΔE up to ${num(p.max_delta_e, 1)}`) : null,
        p.changed_layers ? h('span', {class: 'muted small'}, `layers changed: ${p.changed_layers}`) : null],
      details: (p) => h('div', {class: 'stack small'}, p.reason ? h('p', {}, I18N.tr(p.reason)) : null,
        h('p', {}, link('/analysis/' + (p.replaced_by || p.pair_id), p.replaced_by ? `New measurement — photo #${p.replaced_by}` : 'Open photo'))),
      filters: [{key: 'status', label: 'Result', options: Object.entries(PHOTO).map(([k, [text]]) => [k, text]), test: (p, v) => p.status === v}],
      sorts: [['delta', 'Largest color shift', (a, b) => (b.max_delta_e ?? -1) - (a.max_delta_e ?? -1)], ['order', 'Original order', (a, b) => a.pair_id - b.pair_id]],
      empty: 'No photos were remeasured.'});
    const changes = f ? [...f.appeared.map((x) => ({...x, change: 'appeared'})), ...f.gone.map((x) => ({...x, change: 'gone'})),
      ...f.changed.map((x) => ({...x, change: 'changed'}))] : [];
    const changeList = changes.length ? App.list({items: changes, key: (x) => `${x.change}:${x.id}`,
      row: (x) => [pill(...CHANGE[x.change]), h('span', {class: 'fd-kind fd-' + x.kind}, KIND_ONE[x.kind] || x.kind), h('span', {class: 'lst-text'}, I18N.tr(x.statement))],
      details: (x) => h('div', {class: 'stack small'}, x.was ? h('p', {}, `Before: ${KIND_ONE[x.was.kind] || x.was.kind} — ${I18N.tr(x.was.statement)}`) : null,
        h('p', {}, btn('Open finding', () => route({finding: x.id}), 'btn-small'))),
      filters: [{key: 'change', label: 'Change', options: Object.entries(CHANGE).map(([k, [text]]) => [k, text]), test: (x, v) => x.change === v}]}) : null;
    const listed = f ? ['appeared', 'gone', 'changed'].filter((k) => f.counts[k] > f[k].length) : [];
    const summary = `${when(r.finished_at || r.started_at)} · ${RECHECK_END[r.status] || r.status}`
      + (r.photos.length ? ` · replaced ${count('replaced')}, previous retained ${count('kept')}, errors ${count('failed')}` : '');
    return h('details', {class: 'fd-fold'}, h('summary', {}, 'Last recheck: ' + summary),
      h('div', {class: 'stack'},
        r.error ? h('div', {class: 'alert bad'}, I18N.tr(r.error)) : null,
        facts([['Backup', r.backup ? `${r.backup.path} (${mb(r.backup.bytes)})` : 'not made'],
          ['Photos', `remeasured ${r.done} of ${r.total}` + (r.elapsed_s ? ` in ${duration(r.elapsed_s)}` : '')],
          ['Findings', f ? `run #${f.before_run_id ?? '—'} → #${f.after_run_id}: appeared ${f.counts.appeared}, gone ${f.counts.gone}, changed ${f.counts.changed}`
            : 'not recalculated']]),
        f ? h('div', {class: 'toolbar'}, btn('Show findings needing attention, newest first', () => route({run: '', finding: '', tab: '', state: 'attention',
          sort: 'newest', kind: '', task: '', setup: '', material: ''}), 'btn-small')) : null,
        h('h4', {}, 'Photos'), photos.el,
        changeList ? [h('h4', {}, 'Changes in findings'), changeList.el] : null,
        listed.length ? h('p', {class: 'muted small'}, 'Not all changes are listed: ' + listed.map((k) => `${CHANGE[k][0]} — ${f[k].length} of ${f.counts[k]}`).join(', ')) : null));
  }

  /** The run on one line, «Recalculate now»; what it read, the rules not saved, earlier runs and the schedule in a fold. */
  function runLine(run, runs, schedule, cur, route, recheckBox) {
    const recalc = btn('Recalculate now', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        const r = await post('/analysis/runs');
        toast(`Run #${r.id} completed`, 'ok');
        route({run: '', finding: ''});                           // the new run is the latest
      }
      catch (e) { fail(e); self.disabled = false; }
    }, 'primary btn-small');
    const runSelect = h('select', {'aria-label': 'Run', onChange: (e) => route({run: e.target.value, finding: ''})},
      h('option', {value: ''}, 'latest'), runs.map((r) => h('option', {value: r.id, selected: String(r.id) === cur.run}, `№ ${r.id} · ${when(r.at)} · ${TRIGGER[r.trigger] || r.trigger}`)));
    const alerts = run ? rulesAlerts(run) : [];
    const older = run && runs.length && runs[0].id !== run.id;
    return h('div', {class: 'card stack fd-run'},
      h('div', {class: 'row'}, run ? h('strong', {}, `Run #${run.id}`) : h('strong', {}, 'No runs yet'),
        run ? h('span', {class: 'muted small'}, `${when(run.at)} · ${TRIGGER[run.trigger] || run.trigger}`) : null,
        older ? h('span', {class: 'small'}, pill('previous run', 'warn'), ' ', h('a', {href: '#', onClick: (e) => { e.preventDefault(); route({run: '', finding: ''}); }}, 'to latest')) : null,
        h('span', {class: 'spacer'}), recalc, recheckButton(recheckBox)),
      run ? null : h('p', {class: 'muted small'}, 'Findings are recalculated after each photo acceptance; you can also recalculate now.'),
      recheckBox,
      h('details', {class: 'fd-fold'}, h('summary', {}, 'About the run and schedule' + (alerts.length ? ` · assessment rules not saved: ${alerts.length}` : '')),
        h('div', {class: 'stack'},
          run ? facts([['Input data', `accepted photos ${run.inputs.accepted_pairs} · observations for model ${run.inputs.eligible_observations} · knowledge records ${run.inputs.knowledge_entries}`
            + ` · target colors ${run.inputs.targets} · AI findings ${run.inputs.insights}`],
            ['Found', KINDS.map((k) => `${KIND[k]}: ${run.counts[k] || 0}`).join(' · ')]]) : null,
          alerts,
          h('div', {class: 'toolbar'}, field('Show run', runSelect), h('p', {class: 'toolbar-hint'}, 'Previous runs are retained; their findings can be opened and compared.')),
          scheduleBlock(schedule))));
  }

  /** «Open evidence»: the row opens under its own line and the cursor goes to the first thing the finding rests on. */
  const focusEvidence = (root) => { const box = root && root.querySelector('.fd-evidence'), first = box && box.querySelector('a'); if (first) first.focus(); };
  const openEvidence = (list, f) => list.open(f.key).then(focusEvidence);

  /** The findings of the run as a short list read from the server page by page (REQ-002). */
  function findingsList(cur, keep) {
    const asked = {state: cur.state === 'all' ? '' : (cur.state || 'attention'), kind: cur.kind || '', task: cur.task || '', setup: cur.setup || '', material: cur.material || ''};
    return App.list({
      load: async (s) => {
        const params = Object.entries({...s.filters, sort: s.sort, offset: s.offset, limit: s.limit}).filter(([, v]) => v !== '' && v != null);
        const r = await get(`/analysis/runs/${cur.run || 'latest'}?` + new URLSearchParams(params).toString());
        return {items: r.findings, total: r.matched, counts: r.counts, options: r.options};
      },
      key: (f) => f.key, row, details: (f, list) => findingDetails(f, list.refresh, (x) => openEvidence(list, x)),
      actions: (f, list) => [nextButton(f, (x) => openEvidence(list, x)), ...markButtons(f, list.refresh,
        () => list.open(f.key).then((det) => { const note = det && det.querySelector('textarea'); if (note) note.focus(); }))],
      filters: [{key: 'state', label: 'Status', options: STATES, keepEmpty: true},
        {key: 'kind', label: 'Type', options: KINDS.map((k) => [k, KIND[k]])},
        {key: 'task', label: 'Task', select: true, options: (a) => ((a.options || {}).tasks || []).map((t) => [t, taskName(t)])},
        {key: 'setup', label: 'Laser and lens', select: true, options: (a) => ((a.options || {}).setups || []).map((s) => [s.key, setupName(s)])},
        {key: 'material', label: 'Titanium', select: true, options: (a) => ((a.options || {}).stocks || []).map((s) => [s.key, stockName(s.stock)])}],
      sorts: SORTS, initial: {sort: cur.sort || 'important', filters: asked},
      empty: 'No findings match the selected filters.', className: 'fd-list',
      onChange: (s) => keep({...s.filters, state: s.filters.state || 'all', sort: s.sort === 'important' ? '' : s.sort}),
    });
  }

  /** A finding a link opened (``?finding=<id>``, from the designer): above the list, open, whatever the filters. */
  async function linkedFinding(id, close) {
    const box = h('div', {class: 'card stack fd-linked'});
    const show = async () => {
      const f = await get(`/analysis/findings/${id}`);
      App.fill(box, [h('div', {class: 'row'}, h('h3', {}, `Finding #${f.id}`), h('span', {class: 'muted small'}, `from run #${f.run_id}`),
        h('span', {class: 'spacer'}), markButtons(f, show, () => box.querySelector('textarea').focus()), btn('Close', () => { box.remove(); close(); }, 'btn-small')),
        findingDetails(f, show, () => focusEvidence(box))]);
    };
    try { await show(); } catch (e) { App.fill(box, h('div', {class: 'alert bad'}, e.message || String(e))); }
    return box;
  }

  /** Photo engraving as a queue of the same kind (ux-evidence-summaries-p0 REQ-002): one row for every laser and titanium where one was
      photographed, its kinds under it; the row names the problem (a kind that came out a negative, one not yet measured …), what it
      concerns and ONE recommended step — the first of its kinds the server ranks highest (``recommendation`` of ``/analysis/photo-queue``). */
  const PHOTO_STATUS = {settled: 'search converged', searching: 'search in progress', measured: 'measured, not yet matched', unmeasured: 'not measured', failed: 'unsuccessful'};
  const PHOTO_STEP = {
    open_evidence: (r) => ({label: `Open photo #${r.target.id}`, go: `/analysis/${r.target.id}`}),
    make_plate: () => ({label: 'View proposal', open: true}),
    open_scales: () => ({label: 'Gray scales', go: '/photo-engraving?scales=1'}),
    add_photograph: () => ({label: 'Add photo', go: '/ingest'})};
  const PHOTO_WHY = {failed_look_first: 'Negative or barely visible image: inspect the photo before making a new plate.',
    plate_offered: 'The laboratory proposes a plate to find settings for this mode.', read_the_best: 'Review the photo supporting the best measurement.',
    start_with_scales: 'Start with gray scales; they support tone predictions.', photograph_first: 'First photograph any dot photo engraving.'};
  const kindName = (kind) => PhotoModes.label(kind);
  /** The kinds of a place that still ask something of the operator, the most urgent first (the server's ``rank``). */
  const pending = (place) => place.kinds.filter((k) => k.recommendation && k.recommendation.action !== 'none').sort((a, b) => a.recommendation.rank - b.recommendation.rank);
  function photoList(photo) {
    const keyOf = (k) => `${k.device_id}/${k.lens_id}/${k.material_id}`;
    const urgency = (place) => (pending(place)[0] || {recommendation: {rank: 99}}).recommendation.rank;
    return h('div', {class: 'stack'},
      h('p', {class: 'muted small'}, 'Photo-engraving queue: each laser and titanium combination shows the issue and one recommended step. The best measured settings for each mode, '
        + 'what each setting does, and the plate proposed by the laboratory appear under the row.'),
      App.list({items: photo, key: keyOf, open: photo.length === 1 ? keyOf(photo[0]) : null,
        row: (k) => {
          const first = pending(k)[0];
          const failed = k.kinds.filter((x) => x.status === 'failed');
          return [h('span', {class: 'lst-text'}, `${k.setup} · ${k.titanium}`),
            h('span', {class: 'muted small'}, `modes measured: ${k.kinds.filter((x) => x.best).length} of ${k.kinds.length}`),
            failed.length ? pill(`unsuccessful modes: ${failed.length}`, 'bad') : null,
            k.kinds.some((x) => x.proposal) ? pill('proposal available', 'ok') : null,
            first ? h('span', {class: 'small fd-next-kind', title: PHOTO_WHY[first.recommendation.rule]},
              `Next: ${kindName(first.kind)} — ${PHOTO_STATUS[first.status] || first.status}`) : h('span', {class: 'muted small'}, 'no decisions needed')];
        },
        actions: (k, list) => {
          const first = pending(k)[0];
          if (!first) return [];
          const step = PHOTO_STEP[first.recommendation.action](first.recommendation);
          return [btn(step.label, () => (step.go ? App.go(step.go) : list.open(keyOf(k))), 'primary btn-small fd-recommended')];
        },
        details: (k) => h('div', {class: 'ex-insights'}, PhotoQuality.kindCards(k, {device_id: k.device_id, lens_id: k.lens_id, material_id: k.material_id})),
        sorts: [['urgent', 'Needs decision first', (p, q) => urgency(p) - urgency(q) || `${p.setup} · ${p.titanium}`.localeCompare(`${q.setup} · ${q.titanium}`)],
          ['setup', 'By laser and titanium', (p, q) => `${p.setup} · ${p.titanium}`.localeCompare(`${q.setup} · ${q.titanium}`)]]}).el);
  }

  App.register({id: 'findings', async render(ctx) {
    const cur = {...ctx.query};
    const [runs, schedule, goals, lastRecheck, excluded] = await Promise.all([get('/analysis/runs?limit=60'), get('/analysis/schedule'), get('/application-goals'),
      get('/recheck/latest'), get('/exclusions')]);
    goalNames = Object.fromEntries(goals.map((g) => [g.id, g.name]));
    const run = cur.run ? (runs.find((r) => String(r.id) === cur.run) || await get(`/analysis/runs/${cur.run}?limit=1`).then((r) => r.run)) : runs[0] || null;
    // the list keeps its choices in the address without drawing the screen again; another run draws it again
    const address = () => '/findings?' + new URLSearchParams(Object.entries(cur).filter(([, v]) => v)).toString();
    const keep = (change) => { Object.assign(cur, change); history.replaceState(null, '', '#' + address()); };
    const route = (change) => { Object.assign(cur, change); App.go(address()); };
    let photo = [];
    try { photo = await get('/analysis/photo-queue'); } catch (_) { /* the rest of the screen stands */ }
    const linked = cur.finding ? await linkedFinding(cur.finding, () => keep({finding: ''})) : null;
    const total = run ? KINDS.reduce((n, k) => n + (run.counts[k] || 0), 0) : 0;
    const recheckBox = h('div', {class: 'stack fd-recheck'});
    if (lastRecheck && lastRecheck.status === 'running') followRecheck(recheckBox, lastRecheck);
    else if (lastRecheck) App.fill(recheckBox, recheckReport(lastRecheck, route));
    const findings = h('div', {class: 'stack'}, linked,
      !run ? null : total ? findingsList(cur, keep).el : h('div', {class: 'card empty'}, 'No findings in this run.'));
    const tabs = photo.length ? App.tabs([['findings', 'Findings', findings], ['photo', 'Photo engraving', photoList(photo)]],
      {initial: cur.tab === 'photo' ? 'photo' : 'findings', label: 'Findings', prefix: 'fd', onSelect: (id) => keep({tab: id === 'photo' ? 'photo' : ''})}) : null;
    return h('div', {class: 'stack fd-page'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Findings'),
        h('p', {class: 'sub'}, 'Decision queue: each finding shows the issue, what it concerns, and one recommended step. '
          + 'Improvements, instability, anomalies, gaps, and AI hypotheses; measurements are distinguished from hypotheses.')),
        h('span', {class: 'spacer'}), link('/designer', 'Experiment planner')),
      runLine(run, runs, schedule, cur, route, recheckBox),
      tabs ? [tabs.list, ...tabs.panels] : findings,
      exclusionsBlock(excluded));                                  // the operator's decisions in force: a fold under the queue, not above it
  }});
})();
