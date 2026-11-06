/* Engraving results, comparison evidence, and recipe corrections (DEC-090). */
'use strict';
const VectorReview = (() => {
  const {h, fill, btn, num, link, modal} = App;
  const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);
  const rgb = (c, title) => h('span', {class: 'sw', style: `background:rgb(${c.join(',')})`, title});
  const signed = (v, d = 1) => (v == null ? '—' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d));
  const percent = (share) => `${Math.round((share || 0) * 100)} %`;
  const sq = (mm2) => `${num(mm2 / 100, 1)} cm²`;
  const BASIS = {chart: 'from reference chart', clean: 'relative to clean titanium', 'as-shot': 'as photographed'};
  const CAUSE = {
    highlight: (c) => `layer is lighter than the chart’s white square (L* ${num(c.L, 1)}): glare clipped the color, so the actual color was not measured`,
    basis: (c) => `expected color is ${BASIS[c.promised] || c.promised}, while the result is ${BASIS[c.got] || c.got}: comparison is approximate`,
    relative_photo: () => 'photo has no reference chart: color is relative, not absolute'};
  const NOTE = {
    poor_chart: (n) => `The chart was read imprecisely in this photo (error ${num(n.residual, 1)} ΔE), so smaller differences are not counted as errors.`,
    systematic: (n) => `Nearly all layers shifted in the same direction (median ΔL ${signed(n.dL)}), suggesting photo exposure or titanium batch effects rather than recipes.`};
  const LOST = 'The file was created before the work saved expected colors, and the work was recolored or split afterward. Its expected colors '
    + 'cannot be reconstructed, so no comparison is available. Measured photo layers are listed below; the next file will save its expected colors.';
  const TOP = 5;                                 // the largest differences named first; the rest on request
  const shown = new Map();                       // which engraving to display: a viewer preference, not work state

  // ---- engraving result -----------------------------------------------------------------------------------------------------

  const PHOTO_SETTINGS = {power: 'maximum power, %', min_power: 'minimum power, %', pulse_width: 'pulse width, ns',
    line_interval: 'interval, mm', speed: 'speed, mm/s', frequency: 'frequency, kHz', dither: 'mode'};

  function photoResult(p) {
    const t = p.tone;
    return h('div', {class: 'stack'}, h('h4', {}, p.zone ? `Photo zone ${p.zone}` : p.name),
      (p.changed_settings || []).length ? h('div', {class: 'alert warn'},
        `The engraved settings differ from file #${p.latest_export}: `,
        p.changed_settings.map((k) => `${PHOTO_SETTINGS[k] || k}: ${p.settings[k]} → ${p.latest_settings[k]}`).join('; '),
        '. The comparison uses the engraved settings.') : null,
      p.median_de == null ? h('p', {class: 'small muted'}, 'No scale was measured for these photo layer settings before engraving, so prediction accuracy was not assessed.')
        : h('p', {}, `Photo layer prediction from earlier measurements: median error ${num(p.median_de, 1)} ΔE, maximum ${num(p.max_de, 1)} ΔE.`),
      t ? h('p', {class: 'small'}, `Photo: ${t.levels} of ${t.steps} distinguishable tones; lightness from ${num(t.black_L, 1)} to ${num(t.white_L, 1)} L*.`) : null,
      h('p', {class: 'small muted'}, p.profile_usable
        ? 'Measured tones inform future predictions for this photo layer with the same settings.'
        : 'Measured tones do not inform the prediction because image-to-photo alignment has not been confirmed.'));
  }

  function detail(row) {
    const causes = row.causes.map((c) => h('li', {}, (CAUSE[c.code] || (() => c.code))(c)));
    modal(row.name, h('div', {class: 'stack'},
      h('p', {}, rgb(row.promised_srgb, 'expected'), `Expected: ${App.labText(row.promised_lab)}`),
      h('p', {}, rgb(row.got_srgb, 'actual'), `Actual: ${App.labText(row.got_lab)}`),
      h('p', {}, `ΔE ${num(row.delta_e, 1)} · lightness ${signed(row.dL)} · chroma ${signed(row.dC)}` + (row.dh == null ? '' : ` · hue ${signed(row.dh, 0)}°`)),
      h('p', {class: 'small muted'}, `Expected layer: ${row.promised_name}; area ${sq(row.area_mm2)}.`),
      causes.length ? h('div', {}, h('strong', {}, 'What the measurements show'), h('ul', {}, causes))
        : h('p', {class: 'small muted'}, 'The measurements do not reveal a cause: the layer was measured correctly but the color differed. Titanium or focus may have changed.')),
      [{label: 'Close', cls: 'primary', run: (m) => m.close()}]);
  }

  function rowLine(row) {
    return h('button', {type: 'button', class: 'vw-line vw-review-row', onClick: () => detail(row)},
      h('span', {}, rgb(row.promised_srgb, 'expected'), '→', rgb(row.got_srgb, 'actual'), row.name),
      h('span', {class: 'small ' + (row.beyond ? 'vw-bad' : 'muted')}, `ΔE ${num(row.delta_e, 1)} · ΔL ${signed(row.dL)}`));
  }

  // a photograph opened from here is linked to this work: the form takes its laser, lens and titanium from it
  const uploadLink = (j) => link(`/ingest?plan=${j.id}` + (j.material_id ? `&material=${j.material_id}` : ''), 'Upload a photo for this work');

  /** Compare expected and actual colors; photo layer assessment is separate. */
  function colourSection(j, r) {
    const t = r.summary;
    const rows = [...r.rows].sort((a, b) => b.delta_e - a.delta_e);
    const pic = (promised) => h('figure', {class: 'vw-review-pic'}, h('img', {alt: promised ? 'Work in expected colors' : 'Work in actual colors', loading: 'lazy',
      src: `/api/vector/${j.id}/engraved.png?engraving=${encodeURIComponent(r.engraving_id)}&promised=${promised}&v=${encodeURIComponent(r.reviewed_at)}`}),
      h('figcaption', {class: 'small'}, promised ? 'Expected' : 'Actual'));
    const worst = h('div', {class: 'vw-lines'});
    let all = false;
    const drawWorst = () => {
      fill(worst, (all ? rows : rows.slice(0, TOP)).map(rowLine), rows.length > TOP ? btn(all ? 'Show only largest' : `Show all (${rows.length})`,
        () => { all = !all; drawWorst(); }, 'btn-small') : null);
    };
    drawWorst();
    return h('section', {class: 'stack', 'aria-label': 'Color assessment'}, h('h5', {}, 'Color assessment'),
      r.promise_lost ? h('div', {class: 'alert warn'}, LOST)
      : t.matched === 0 ? h('div', {class: 'alert warn'}, 'No engraved file layers matched this work’s file layers by settings. This is a different file (it was edited in LightBurn '
        + 'or made from another work), so there is nothing to compare.')
        : h('p', {}, `Matched ${t.matched} of ${t.promised} expected layers. Area-weighted mean difference is ${num(t.mean_delta_e, 1)} ΔE; ${t.beyond_layers} layers differ noticeably `
          + `(${percent(t.area_share_beyond)} of area). Threshold: ${num(r.limit, 1)} ΔE.`),
      ...r.notes.map((n) => h('div', {class: 'alert'}, (NOTE[n.code] || (() => n.code))(n))),
      t.matched ? h('div', {class: 'vw-review-pics'}, pic(true), pic(false)) : null,
      rows.length ? h('div', {class: 'stack'}, h('h6', {}, 'Largest differences'), worst) : null,
      r.not_engraved.length ? h('details', {class: 'vw-details'}, h('summary', {}, `Expected but not found in the photo (${r.not_engraved.length})`),
        h('div', {class: 'vw-lines'}, r.not_engraved.map((n) => h('div', {class: 'vw-line'}, h('span', {}, n.name), h('span', {class: 'small muted'}, sq(n.area_mm2)))))) : null,
      r.unmatched.length ? h('details', {class: 'vw-details'}, h('summary', {}, `In the photo but not in the work file (${r.unmatched.length})`),
        h('div', {class: 'vw-lines'}, r.unmatched.map((n) => h('div', {class: 'vw-line'}, h('span', {}, n.name))))) : null);
  }

  /** Assess photo layers separately; omit the section when none exist. */
  function photoSection(r) {
    return (r.photo || []).length ? h('section', {class: 'stack', 'aria-label': 'Photo layer assessment'}, h('h5', {}, 'Photo layer assessment'), ...r.photo.map(photoResult)) : null;
  }

  function resultBlock(j) {
    const head = h('h4', {}, 'Engraving result');
    const reviews = j.reviews || [];
    if (!reviews.length) {
      return h('div', {class: 'stack'}, head, h('p', {class: 'small muted'},
        'No result photo has been accepted for this work yet. Engrave the work file without editing its layers in LightBurn, photograph the result, and upload it below. '
        + 'An expected-to-actual comparison will appear here and the finding will be saved in the work.'), h('p', {}, uploadLink(j)));
    }
    const current = reviews.find((r) => r.engraving_id === shown.get(j.id)) || reviews[0];
    const body = h('div', {class: 'stack'});
    const label = (r) => `${r.photo_name} · ${r.export_number ? `file #${r.export_number}` : 'work not exported'} · ${when(r.reviewed_at)}`;
    const picker = h('select', {'aria-label': 'Engraving', onChange: (ev) => { shown.set(j.id, ev.target.value); fill(body, content(ev.target.value)); }},
      reviews.map((r) => h('option', {value: r.engraving_id, selected: r.engraving_id === current.engraving_id}, label(r))));
    function content(id) {
      const r = reviews.find((x) => x.engraving_id === id) || current;
      return [h('p', {class: 'small'}, `Photo ${r.photo_name} · ${when(r.reviewed_at)} · ` + (r.export_number ? `file #${r.export_number}` : 'work not yet exported')),
        h('p', {class: 'small' + (r.basis.kind === 'saved' ? ' muted' : ''), role: r.basis.kind === 'saved' ? null : 'note'}, Lifecycle.basisNote(r.basis)),
        colourSection(j, r), photoSection(r)];
    }
    fill(body, content(current.engraving_id));
    return h('div', {class: 'stack'}, head, App.field('Engraving', picker), body, h('p', {class: 'small'}, uploadLink(j)));
  }

  // ---- work colors after new measurements ---------------------------------------------------------------------------------------

  /** Track replacements for undo while the work remains unchanged. */
  const replaced = new Map();
  const seen = new Map();                        // undo depth from the last render; the server response renders before ``run`` returns
  const intact = (j, done) => (done.depth == null || done.depth === j.undo)
    && done.ops.every((o) => ((j.colours || []).find((c) => c.index === o.op.colour) || {}).entry_id === o.op.entry_id);

  /** Apply each replacement as an ordinary color edit. */
  async function replace(j, run, ops) {
    const done = {ops: [], depth: null};
    replaced.set(j.id, done);
    for (const one of ops) {
      done.ops.push(one);                          // record first: the server response renders before ``run`` returns
      if (!(await run(one.op))) { done.ops.pop(); break; }
      done.depth = seen.get(j.id);
    }
    if (!done.ops.length && replaced.get(j.id) === done) replaced.delete(j.id);
  }

  function replacement(j, p, run) {
    const apply = btn('Replace', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      await replace(j, run, [{op: {op: 'set_colour', colour: p.colour, entry_id: p.entry_id}, de: p.delta_e_proposed}]);
      self.disabled = false;
    }, 'btn-small');
    return h('div', {class: 'vw-line'},
      h('span', {class: 'small'}, rgb(p.srgb, 'original color'), p.delta_e_now == null ? 'color not measured' : `ΔE from original ${num(p.delta_e_now, 1)}`,
        ' → ', rgb(p.entry_srgb, 'proposed'), `${num(p.delta_e_proposed, 1)}`), apply);
  }

  /** Offer undo while the recorded replacements remain the latest work changes. */
  function undoNote(j, run) {
    const done = replaced.get(j.id);
    if (!done) return null;
    if (!intact(j, done)) { replaced.delete(j.id); return null; }
    const n = done.ops.length;
    return h('div', {class: 'alert ok row', role: 'status'}, h('span', {}, n > 1 ? `Colors replaced: ${n}.` : `Original color replaced with the nearest measured color (ΔE ${num(done.ops[0].de, 1)}).`,
      ' The engraved file was not changed.'),
      btn('Undo replacement', async (ev) => {
        const self = ev.currentTarget;
        self.disabled = true;
        replaced.delete(j.id);
        for (let i = 0; i < n; i++) { if (!(await run({op: 'undo'}))) break; }
        self.disabled = false;
      }, 'btn-small'));
  }

  function driftBlock(j, run) {
    const a = j.attention || null;
    const head = h('h4', {}, 'Current work prediction: colors after new measurements');
    const note = h('p', {class: 'small muted'}, 'New measurements update only the current work prediction. They do not change the engraved file or the expected colors in an exported file.');
    if (!a) return h('div', {class: 'stack'}, head, note, undoNote(j, run), h('p', {class: 'small muted'}, 'No file has been created from this work yet, so no colors were promised; the preview already uses the latest measurements.'));
    if (!a.layers.length) return h('div', {class: 'stack'}, head, note, undoNote(j, run), h('p', {class: 'small muted'},
      'Layer colors match the last file’s expected colors; the work’s recipes have not changed noticeably since export.'));
    const all = a.layers.flatMap((l) => l.proposals.filter((p) => p.entry_id).map((p) => ({op: {op: 'set_colour', colour: p.colour, entry_id: p.entry_id}, de: p.delta_e_proposed})));
    const every = all.length > 1 ? btn(`Apply all replacements (${all.length})`, async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      await replace(j, run, all);
      self.disabled = false;
    }, 'btn-small') : null;
    return h('div', {class: 'stack'}, head, note, undoNote(j, run),
      h('div', {class: 'alert warn'}, `Colors in ${a.layers.length} of ${a.layers_total} file layers differ from the expected colors by more than ${num(a.visible_de, 0)} ΔE (${percent(a.area_share)} of the area).`
        + ' The engraved file stays unchanged; replacement edits only the work and can be undone.'),
      a.approximate ? h('p', {class: 'small muted'}, 'The file was created before expected colors were saved; they were reconstructed from the work layers as exported.') : null,
      every,
      a.layers.map((l) => h('div', {class: 'stack vw-drift'},
        h('div', {class: 'vw-line'}, h('span', {}, rgb(l.was_srgb, 'expected'), l.missing ? ' → color no longer measured' : [' → ', rgb(l.now_srgb, 'current')], ` ${l.name}`),
          h('span', {class: 'small vw-bad'}, l.delta_e == null ? sq(l.area_mm2) : `ΔE ${num(l.delta_e, 1)} · ${sq(l.area_mm2)}`)),
        ...l.proposals.filter((p) => p.entry_id).map((p) => replacement(j, p, run)),
        l.proposals.some((p) => !p.entry_id) ? h('p', {class: 'small muted'}, 'There is no closer measured color for the remaining original colors in this layer.') : null)));
  }

  /** Result tab: latest engraving and colors after new measurements. ``run`` queues a color edit. */
  function view(j, run) {
    seen.set(j.id, j.undo);
    return h('div', {class: 'stack'}, resultBlock(j), driftBlock(j, run));
  }

  /** Tab label: number of layers that differ from expected colors. */
  function tabLabel(j) {
    return j.attention && j.attention.layers.length ? `Result · ⚠ ${j.attention.layers.length}` : 'Result';
  }

  // ---- lists ---------------------------------------------------------------------------------------------------------------------

  /** Work-list card lines describing changes and the latest engraving. */
  function cardLines(w) {
    const lines = [];
    if (w.attention && w.attention.layers) lines.push(h('p', {class: 'small vw-bad'}, `⚠ ${w.attention.layers} layer colors differ from the file’s expected colors (${percent(w.attention.area_share)} of area)`));
    if (w.review) {
      lines.push(h('p', {class: 'small'}, w.review.matched
        ? `Engraving result (${w.review.photo_name}): ΔE ${num(w.review.mean_delta_e, 1)}, ${w.review.beyond_layers} of ${w.review.matched} layers differ noticeably`
        : w.review.promise_lost ? `Photo ${w.review.photo_name}: expected colors were not saved, so no comparison is available`
        : `Photo ${w.review.photo_name}: layers did not match this work’s file`));
    }
    return lines;
  }

  /** Photo report card for the work linked to the photo. */
  function reportCard(wr) {
    if (!wr) return null;
    const s = wr.review.summary;
    return h('div', {class: 'card stack'}, h('h3', {}, `Finding for work “${wr.work}”`),
      s.matched ? h('p', {}, `Matched ${s.matched} of ${s.promised} expected layers; mean difference ${num(s.mean_delta_e, 1)} ΔE; ${s.beyond_layers} layers differ noticeably `
        + `(${percent(s.area_share_beyond)} of area).`) : h('p', {}, wr.review.promise_lost ? LOST : 'No layers in this file matched the work file by settings.'),
      wr.review.basis ? h('p', {class: 'small'}, Lifecycle.basisNote(wr.review.basis)) : null,
      ...wr.review.notes.map((n) => h('p', {class: 'small muted'}, (NOTE[n.code] || (() => n.code))(n))),
      ...(wr.review.photo || []).map(photoResult),
      h('div', {class: 'row'}, link('/vector?plan=' + wr.plan_id, 'Open work: comparison and replacements')));
  }

  return {view, tabLabel, cardLines, reportCard};
})();
