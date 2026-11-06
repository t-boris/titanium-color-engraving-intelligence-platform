/* Match image colors to validated and production titanium colors (REQ-004, REQ-042). Unreachable colors must be replaced or excluded before creating a plan. */
'use strict';
(() => {
  const {h, btn, link, pill, get, post, patch, put, go, table, num, labText, swatch} = App;
  const {startForm, replaceDialog, questionedDialog, seconds} = ArtworkParts;
  const HOW = {fastest_within_threshold: 'fastest within threshold', nearest: 'nearest', replaced: 'operator replacement'};
  const STATUS = {matched: ['Matched', 'ok'], unreachable: ['Unreachable', 'bad'], replaced: ['Manually replaced', 'ok'], excluded: ['Excluded', '']};

  App.register({id: 'artwork', async render(ctx) {
    const id = ctx.query.plan || ctx.query.id;
    if (!id) {
      const lists = await App.hardwareLists();
      if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Add a laser first'), link('/devices', 'Lasers'));
      return h('div', {class: 'stack'}, h('h2', {}, 'Color engraving'), startForm(lists, {...ctx, start: await App.contextStart(ctx.query)}));
    }
    const reload = () => App.render();
    const plan = await get('/plans/' + id), palette = await get(`/discrete/${id}/palette`);
    const unresolved = plan.matches.filter((m) => m.status === 'unreachable').length;
    const active = plan.matches.filter((m) => m.status === 'matched' || m.status === 'replaced').length;
    // the threshold and the time limit are read as the server reads them (conversion._threshold, colormap.time_limit); a wrong box is said beside itself and keeps what
    // was typed. What the server refuses about a decision on a colour stands above the table, with the plan as it was (ux-save-feedback-p0, REQ-003)
    const form = Forms.create();
    const thrField = form.add('threshold', 'ΔE threshold', Forms.numberInput(Forms.QUANTITIES.deltaE, {value: plan.threshold}), {quantity: 'deltaE', required: true});
    const timeField = form.add('max_time', 'Maximum engraving time', Forms.numberInput(Forms.QUANTITIES.maxTime, {value: plan.max_time ?? '', placeholder: 'no limit'}), {quantity: 'maxTime'});
    const bar = Forms.notice({what: 'Plan change', kept: 'The plan remains unchanged.'});
    const finish = Forms.notice({what: 'Plan creation', kept: 'The plan remains a draft.'});
    const edit = async (changes) => { bar.clear(); try { await patch('/discrete/' + id, changes); reload(); } catch (e) { bar.fail(e); } };
    const rows = plan.matches.map((m) => {
      const [label, kind] = STATUS[m.status];
      // the titanium colour the match was tested against, with its three estimates (REQ-002, REQ-004): carried by the match;
      // a plan matched before the match carried them takes them from the palette entry
      const entry = palette.find((x) => x.id === (m.knowledge_id ?? m.candidate_id));
      const t = m.titanium || (entry ? {lab: entry.lab, confidence: entry.confidence, expected_delta_e: entry.expected_delta_e, stability: entry.stability} : null);
      const back = btn('Return to matching', async () => {
        const rep = Object.fromEntries(Object.entries(plan.replacements).filter(([k]) => k !== m.source_key));
        await edit({exclusions: plan.exclusions.filter((k) => k !== m.source_key), replacements: rep});
      });
      const act = m.status === 'excluded' ? back : h('span', {class: 'row'}, btn('Replace', () => replaceDialog(plan, m, palette, reload)),
        btn('Exclude', () => edit({exclusions: [...plan.exclusions, m.source_key]})));
      const shown = t && m.status !== 'excluded';
      const time = m.time_s_per_cm2 ?? (entry ? entry.time_s_per_cm2 : null);
      return [h('span', {}, swatch(m.source_lab), labText(m.source_lab)), pill(label, kind),
        shown ? h('span', {}, m.status === 'unreachable' ? 'nearest: ' : '', swatch(t.lab), labText(t.lab),
          m.how && HOW[m.how] && m.status !== 'unreachable' ? h('div', {class: 'muted small'}, HOW[m.how]) : null) : '—',
        shown ? seconds(time) : '—',
        m.distance == null ? '—' : num(m.distance), shown ? num(t.expected_delta_e) : '—',
        m.match_error == null ? '—' : h('span', {}, num(m.match_error), m.match_error > plan.threshold ? ` > ${plan.threshold}` : ` ≤ ${plan.threshold}`),
        shown ? num(t.confidence) : '—', shown ? (t.stability.assessed ? 'variance ' + num(t.stability.variance) : 'not assessed') : '—', act];
    });
    const markerBtn = btn(plan.markers_enabled ? 'Disable registration markers' : 'Enable registration markers',
      async () => { bar.clear(); try { await put(`/plans/${id}/markers`, {enabled: !plan.markers_enabled}); reload(); } catch (e) { bar.fail(e); } });
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Color engraving · ' + plan.name),
        h('p', {class: 'sub'}, `Current ΔE threshold: ${plan.threshold}. It is compared with the distance to the target plus the record’s expected error (DEC-030).`)),
      h('span', {class: 'spacer'}), link(`/designer?device=${plan.device_id}&lens=${App.lensParam(plan.lens_id)}`, 'Experiment targets')),
      palette.length ? null : h('div', {class: 'alert warn'}, 'No validated or production colors exist for this laser and lens; all colors are unreachable.'),
      h('div', {class: 'card stack'}, h('div', {class: 'toolbar'}, thrField, timeField,
        btn('Match colors', async () => {
          const v = form.collect();
          if (!v) return;
          bar.clear();
          try { await patch('/discrete/' + id, {threshold: v.threshold, max_time: v.max_time}); reload(); } catch (e) { form.fail(e); }
        }),
        btn('Include questioned settings in this plan', () => questionedDialog(plan, reload)), markerBtn), form.error, bar.error),
      h('div', {class: 'card'}, h('h3', {}, 'Image colors'),
        h('p', {class: 'muted small'}, `Expected match error = ΔE to target + expected titanium record error. A color matches when this does not exceed ${plan.threshold}. `,
          'The fastest eligible color by estimated engraving time per cm² is chosen; the nearest breaks ties',
          plan.max_time ? `; recipes slower than ${plan.max_time} s/cm² are not selected automatically.` : '.'),
        table(['Source color', 'Status', 'Titanium color', 'Time per cm²', 'ΔE to target', 'Expected record error', 'Expected match error', 'Confidence', 'Stability', ''], rows)),
      // The preview URL changes after each color matching decision.
      h('div', {class: 'card stack'}, h('h3', {}, 'Image in titanium colors'), h('div', {class: 'grid g2'},
        h('figure', {}, h('img', {src: `/api/plans/${id}/source-image`, style: 'width:100%', alt: 'Source image'}), h('figcaption', {class: 'muted small'}, 'Source image')),
        h('figure', {}, h('img', {src: `/api/plans/${id}/banding.png?v=${encodeURIComponent(plan.matches.map((m) => `${m.status}${m.knowledge_id}`).join('.'))}`,
          style: 'width:100%;image-rendering:pixelated', alt: 'Image in matched titanium colors'}),
          h('figcaption', {class: 'muted small'}, 'Matched titanium colors; unreachable colors are hatched red and exclusions are white')))),
      unresolved ? h('div', {class: 'alert bad'}, `Unresolved colors: ${unresolved}. Replace or exclude each one before creating a plan. They are already planner targets.`) : null,
      active === 0 && !unresolved ? h('div', {class: 'alert warn'}, 'All regions are excluded; plan creation is disabled.') : null,
      h('div', {class: 'row'}, btn('Create plan', async (ev) => {
        const self = ev.currentTarget;
        self.disabled = true;
        finish.clear();
        try { await post(`/discrete/${id}/finalize`); go('/plans/' + id); } catch (e) { finish.fail(e); self.disabled = false; }
      }, 'primary', unresolved > 0 || active === 0)), finish.error);
  }});
})();
