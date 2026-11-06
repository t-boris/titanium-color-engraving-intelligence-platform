/* Color knowledge: evidence, history and operator decisions (REQ-005, DEC-006, DEC-011). Promotion to production requires explicit approval. */
'use strict';
const KnowledgeView = (() => {
  const {h, btn, field, link, pill, get, post, modal, num, labText, swatch, facts} = App;
  const STAGE = {measured: 'Measured', candidate: 'Candidate', repeated: 'Repeated', validated: 'Validated', production: 'Production'};
  const EVENT = {created: 'created', promoted: 'promoted automatically', questioned: 'marked questioned', approved: 'approved for production',
    demoted: 'demoted manually', confirmed: 'flag cleared', rollback: 'rollback'};
  const stab = (s) => (s.assessed ? `variance ${num(s.variance)}` : 'not assessed');
  /** Repeatability compares chart-corrected photographs of the same engraving (REQ-009). */
  const rig = (r) => (r && r.assessed
    ? `ΔE ${num(r.mean_delta_e)} average, up to ${num(r.max_delta_e)} · photographs of one engraving: ${r.photos}`
    : 'not assessed: requires repeat photographs of one engraving corrected using a reference chart');
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 0)} kHz · ${num(p.speed, 0)} mm/s`;

  /** Open a decision dialog, validate fields, and report server refusals without discarding input. */
  function decision(label, body, run, cls, form = null) {
    return btn(label, () => modal(label, h('div', {class: 'stack'}, ...body, form ? form.error : null), [
      {label: 'Cancel', run: (m) => m.close()},
      {label, cls: cls || 'primary', run: async (m) => {
        const values = form ? form.collect() : {};
        if (!values) return;
        try { await run(values); } catch (e) { if (!form) throw e; form.fail(e); return; }
        m.close(); App.render();
      }}]));
  }

  function actions(k, kid) {
    const acts = [];
    if (k.stage === 'validated') {
      acts.push(decision('Approve for production', [h('p', {}, 'A color becomes production-ready only through your explicit approval.')],
        () => post(`/knowledge/${kid}/approve`, {confirm: true})));
    }
    if (k.stage === 'production') {
      const form = Forms.create();
      const to = h('select', {}, ['validated', 'repeated', 'candidate', 'measured'].map((x) => h('option', {value: x}, STAGE[x])));
      acts.push(decision('Demote manually', [form.add('to', 'New stage', to, {required: true}),
        form.add('why', 'Reason', h('input', {placeholder: 'reason'}), {raw: true, help: 'optional; without a reason, history records “manual demotion”'})],
      (v) => post(`/knowledge/${kid}/demote`, {confirm: true, to_stage: v.to, reason: v.why}), 'danger', form));
    }
    if (k.counted_from) {
      acts.push(decision('Undo “count from last engraving”', [h('p', {}, 'Older engravings of this recipe will count again; knowledge, findings and work '
        + 'will be recalculated.')], () => post(`/exclusions/${k.counted_from.id}/revoke`, {})));
    }
    if (k.questioned) {
      acts.push(decision('Confirm record', [h('div', {class: 'alert warn'}, I18N.tr(k.doubt.reason)),
        SourceRefs.observations(k.doubt.observation_ids)], () => post(`/knowledge/${kid}/confirm-questioned`)));
    }
    return acts;
  }

  /** Show the operator’s count-from decision and excluded older engravings. */
  function countedFrom(x) {
    const kept = x.kept || {};
    const at = (iso) => (iso ? new Date(iso).toLocaleDateString('en-US') : '—');
    const photos = kept.pair_ids || [];
    const long = photos.length > SourceRefs.SHORT;                 // a few photographs are named in the sentence; many are a count with a list (ux-growing-collections-p0 REQ-002)
    return h('div', {class: 'alert warn small'}, `Counts from engraving${kept.title ? ` “${kept.title}”` : ''} dated ${at(kept.when)}`
      + (photos.length && !long ? ` (photos #${photos.join(', #')})` : '') + `; older engravings excluded: ${(x.engraving_ids || []).length}. `
      + `Operator decision dated ${at(x.created_at)}` + (x.note ? `: “${x.note}”` : '') + '.',
    long ? SourceRefs.photos(photos, {label: 'Photographs of this engraving'}) : null);
  }

  async function render(kid) {
    const k = await get('/knowledge/' + kid + '?history_limit=0');          // the events come a page at a time from the list below, not all with the entry
    const s = k.summary;
    const history = KnowledgeHistory.list(kid, {labels: {STAGE, EVENT}, stage: k.stage});
    await history.ready;
    const back = `/colors?device=${k.device_id}&lens=${App.lensParam(k.lens_id)}`;
    const ids = s ? s.observation_ids : [];
    return h('div', {class: 'os kn'},
      h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: '#' + back}, '← Back to color model'), h('h2', {}, 'Color knowledge'), pill(STAGE[k.stage], k.stage === 'production' ? 'ok' : ''),
        h('span', {class: 'spacer'}), h('a', {class: 'btn btn-small', href: `#/setup?tab=rules&device=${k.device_id}&lens=${App.lensParam(k.lens_id)}`}, 'Assessment rules')),
      k.questioned ? h('div', {class: 'alert bad kn-alert'}, [h('strong', {}, 'Questioned. '), I18N.tr(k.doubt.reason)]) : null,
      h('div', {class: 'os-body kn-body'},
        h('section', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Details')),
          h('div', {class: 'os-scroll stack'}, facts([
            ['Stage', pill(STAGE[k.stage], k.stage === 'production' ? 'ok' : '')],
            ['Settings', params(k.parameters) + ` · pulse ${k.parameters.pulse_width} · spacing ${k.parameters.line_interval} · passes ${k.parameters.passes}`]]),
          // REQ-001 of ux-evidence-summaries-p0: the colour and how far it is trusted on the first level (every observation of an entry is
          // chart-corrected); Lab and the figures of the calculation are one fold away
          s ? EvidenceSummary.summary({...s, measurement: 'calibrated', engravings: s.independent_engravings}, {lead: swatch(s.lab)}) : null,
          EvidenceSummary.disclosure('Calculation details: Lab color, confidence and expected error', facts([
            ['Color', s ? h('span', {}, swatch(s.lab), labText(s.lab)) : '—'],
            ['Independent engravings', s ? s.independent_engravings : '—'], ['Confidence', s ? num(s.confidence) : '—'],
            ['Color agreement', s ? App.agreed(s.agreement) + (s.caution ? ` · ${App.CAUTION[s.caution]}` : '') : '—'],
            ['Expected ΔE error', s ? num(s.expected_delta_e) : '—'], ['Stability', s ? stab(s.stability) : '—'],
            ['Capture setup repeatability', s ? rig(s.rig_repeatability) : '—']])),
          s && s.attribution_note ? h('div', {class: 'alert warn'}, I18N.tr(s.attribution_note)) : null,
          k.counted_from ? countedFrom(k.counted_from) : null, h('div', {class: 'row'}, actions(k, kid)),
          // Explain the terms by their purpose; the technical identifier stays in the disclosure (ux-save-feedback-p0, REQ-003).
          h('div', {class: 'stack kn-terms'}, Terms.note('knowledge', kid), Terms.note('stage'), Terms.note('basis')))),
        h('div', {class: 'kn-right'},
          h('section', {class: 'os-col kn-history'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'History'), pill(k.history_total ?? k.history.length)), h('div', {class: 'os-scroll'}, history.el)),
          s ? h('section', {class: 'os-col kn-evidence'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Supporting observations'), pill(ids.length)),
            h('div', {class: 'os-scroll'}, SourceRefs.observations(ids, {label: 'Observation IDs'}))) : null)));
  }
  return {render, STAGE, stab, rig, params};
})();
