/* Photo engraving quality findings, measurements, and suggested experiments. */
'use strict';
const PhotoQuality = (() => {
  const {h, fill, btn, pill, get, post} = App;
  // toast, go and fail join App later (dialogs.js, router.js): taken when used
  const made = (plate) => { App.toast(`Created: ${plate.name}`, 'ok'); App.go('/experiment/plan-' + plate.plan_id); };
  const value = (v, d = 2) => (v == null ? '—' : String(+(+v).toFixed(d)).replace('.', ','));
  const signed = (v, d = 1) => (v > 0 ? '+' : v < 0 ? '−' : '') + value(Math.abs(v), d);
  const pct = (share) => `${value(share * 100, 0)} %`;
  const copiesOf = (n) => `${n} ${n === 1 ? 'copy' : 'copies'}`;
  const SETTING = {power: 'power', min_power: 'Min', speed: 'speed', frequency: 'frequency', pulse_width: 'pulse width',
    line_interval: 'line interval', dot_width: 'dot width correction', dither: 'mode', passes: 'passes', global_passes: 'global passes'};
  const UNIT = {power: ' %', min_power: ' %', speed: ' mm/s', frequency: ' kHz', pulse_width: ' ns', line_interval: ' mm', dot_width: ' mm'};
  const DIGITS = {power: 1, min_power: 1, speed: 0, frequency: 0, pulse_width: 0, line_interval: 4, dot_width: 3};
  /** Setting value with unit; an unset dot width correction is off. */
  const setting = (key, v) => (key === 'dither' ? PhotoModes.label(v) : v == null ? (key === 'dot_width' ? 'off' : '—') : value(v, DIGITS[key] ?? 2) + (UNIT[key] || ''));
  const changeText = (c) => `${SETTING[c.setting] || c.setting} ${setting(c.setting, c.from)} → ${setting(c.setting, c.to)}`;
  /** Source of dot settings: a color-map fill or a photographed engraving, with estimates identified. */
  const fromPhoto = (r) => !!r && r.source === 'photo';
  const recipeFrom = (r) => (!fromPhoto(r) ? 'from color map' : !r.photo ? 'estimated'
    : `${r.basis === 'estimate' ? 'estimated from photo' : 'from photo'} #${r.photo.pair_id} (${PhotoModes.label(r.photo.kind)})`);
  /** Suggested setting and direction for a finding (``PRIOR_MOVES``). */
  const moveText = (m) => (m.setting === 'dither' ? `mode → ${PhotoModes.label(m.to)}` : `${SETTING[m.setting] || m.setting} ${m.direction === 'up' ? 'increase' : 'decrease'}`);
  const FINDING = {
    good: (f) => [`Tone is good (score ${value(f.value, 2)})`, 'ok'],
    flat: (f) => [`Low contrast: black-to-white range only ${value(f.value, 0)} L*`, 'warn'],
    reversed: (f) => [`Tone reverses: darker gray came out lighter in ${f.value.length} ${f.value.length === 1 ? 'step' : 'steps'}`, 'bad'],
    shadows_blocked: (f) => [`Blocked shadows: everything darker than ${pct(f.value)} gray produces one tone`, 'warn'],
    highlights_lost: (f) => [`Lost highlights: everything lighter than ${pct(f.value)} gray produces one tone`, 'warn'],
    midtones_dark: () => ['Midtones are darker than the image', 'warn'],
    midtones_light: () => ['Midtones are lighter than the image', 'warn'],
    detail_lost: (f) => [`Blurred details: fine details (0.4 mm) retained at ${pct(f.value)}`, 'warn'],
    grainy: (f) => [`Grainy: ±${value(f.value, 1)} L* variation in flat image areas`, 'warn'],
  };
  /** A finding and its suggested adjustment, based on process experience until measured. */
  function findingLine(f) {
    const [text, tone] = (FINDING[f.code] || (() => [f.code, 'warn']))(f);
    return h('li', {}, pill(text, tone), f.moves && f.moves.length
      ? h('span', {class: 'small'}, ` Suggested changes: ${f.moves.map(moveText).join(', ')}`, h('span', {class: 'muted'}, f.basis === 'prior' ? ' (based on process experience)' : ''))
      : f.code === 'reversed' ? h('span', {class: 'small muted'}, ' Dots at one power do not reverse on their own: first check the photo for glare, dust, or borders.') : null);
  }
  /** Tone and detail measurements for one photo engraving. */
  function toneText(q) {
    const t = q.tone;
    const d = q.detail;
    const scales = d && (d.scales || []).filter((x) => x.kept != null);
    const detail = !d ? '' : scales && scales.length > 1
      ? ` Detail retained: ${scales.map((x) => `${value(x.mm, 1)} mm — ${pct(x.kept)}`).join(', ')}${d.grain_L != null ? `; grain ±${value(d.grain_L, 1)} L*` : ''}.`
      : d.kept != null ? ` Fine details (0.4 mm) retained at ${pct(d.kept)}${d.grain_L != null ? `, grain ±${value(d.grain_L, 1)} L*` : ''}.` : '';
    return `Distinguishable tones: ${t.levels} of ${t.steps}; black-to-white range ${value(t.range_L, 0)} L* (${value(t.black_L, 0)} → ${value(t.white_L, 0)}), `
      + `mean L* ${value(t.mean_L, 0)}.${detail}`;
  }

  /** Review-layer findings: score, tone, detail, issues, and suggested changes. */
  function layerBox(name, q) {
    if (!q) return null;
    return h('div', {class: 'stack pq-layer'},
      h('div', {class: 'row'}, h('strong', {}, I18N.name(name)), pill(`score ${value(q.score, 2)}`, q.score >= 0.7 ? 'ok' : q.score >= 0.4 ? 'warn' : 'bad'),
        h('span', {class: 'muted small'}, q.tone.measured_by === 'grey ramp' ? 'from grayscale strip' : 'from image')),
      h('p', {class: 'small'}, toneText(q)),
      h('ul', {class: 'small pq-findings'}, q.findings.map(findingLine)));
  }

  /** Compare a changed copy with the first by tone, highlights, shadows, and detail. */
  function effectText(e) {
    const parts = [];
    if (e.mean_L != null && Math.abs(e.mean_L) >= 0.5) parts.push(e.mean_L > 0 ? `lighter by ${value(e.mean_L, 1)} L*` : `darker by ${value(-e.mean_L, 1)} L*`);
    if (e.range_L != null && Math.abs(e.range_L) >= 1) parts.push(`contrast ${signed(e.range_L, 0)} L*`);
    if (e.shadows_blocked != null && Math.abs(e.shadows_blocked) >= 0.05) parts.push(e.shadows_blocked < 0 ? `shadows opened by ${pct(-e.shadows_blocked)}` : `shadows blocked by a further ${pct(e.shadows_blocked)}`);
    if (e.highlights_lost != null && Math.abs(e.highlights_lost) >= 0.05) parts.push(e.highlights_lost < 0 ? `highlights recovered by ${pct(-e.highlights_lost)}` : `highlights lost by a further ${pct(e.highlights_lost)}`);
    if (e.levels) parts.push(`tones ${signed(e.levels, 0)}`);
    if (e.kept != null && Math.abs(e.kept) >= 0.03) parts.push(e.kept > 0 ? `sharper (+${pct(e.kept)} detail)` : `softer (−${pct(-e.kept)} detail)`);
    return parts.length ? parts.join(', ') : 'almost no difference';
  }

  /** Compare settings-plate copies and propose the next plate. */
  function variationsBox(v, pairId, accepted) {
    if (!v) return null;
    const best = v.ranked[0];
    const next = v.next ? btn('Create next plate', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { made(await post(`/pairs/${pairId}/next-variations`, {})); } catch (e) { App.fail(e); self.disabled = false; }
    }, 'primary btn-small') : null;
    if (next && !accepted) { next.disabled = true; next.setAttribute('title', 'Accept the review first: the next plate is based on the best copy'); }
    return h('div', {class: 'stack pq-variations'},
      h('h3', {}, 'Compare copies'),
      h('p', {}, h('strong', {}, `Best: copy ${v.best_label}`), ` (score ${value(best.score, 2)}${v.best === 1 ? ': the work settings are already best' : ''}).`),
      h('ol', {class: 'small'}, v.ranked.map((c) => h('li', {}, `${c.label} — ${value(c.score, 2)}`,
        c.findings.length && c.findings[0].code !== 'good' ? h('span', {class: 'muted'}, ' · ' + c.findings.map((f) => (FINDING[f.code] ? FINDING[f.code](f)[0] : f.code)).join('; ')) : null))),
      v.effects.length ? h('div', {class: 'stack'}, h('h4', {}, 'Effect of each change (compared with copy 1)'),
        h('ul', {class: 'small'}, v.effects.map((e) => h('li', {}, h('strong', {}, e.changed.map(changeText).join(', ') || e.label), ': ', effectText(e))))) : null,
      v.settled ? h('p', {class: 'alert ok small'}, 'The search converged: the first copy remained best after small changes. These are the best settings for this mode and image.')
        : h('p', {class: 'small'}, next, ` Next plate: the same image around copy ${v.best}, with half-sized changes (step ${value(v.next.step, 3)} of the initial changes). `
          + 'Each plate brings the settings closer to the best result.'));
  }

  const DIRECTION = {darker: 'Darker', lighter: 'Lighter', sharper: 'Sharper', softer: 'Softer'};
  /** Measured effects of doubling a setting, or increasing dot correction by 0.01 mm. */
  function effectLine(key, e) {
    const per = e.per === 'doubling' ? 'doubled' : '+0.01 mm';
    const parts = [];
    if (e.mean_L) parts.push(e.mean_L.median > 0 ? `lighter by ${value(e.mean_L.median, 1)} L*` : `darker by ${value(-e.mean_L.median, 1)} L*`);
    if (e.kept) parts.push(e.kept.median > 0 ? `detail +${pct(e.kept.median)}` : `detail −${pct(-e.kept.median)}`);
    if (e.score) parts.push(`score ${signed(e.score.median, 2)}`);
    return h('li', {}, `${SETTING[key] || key} ${per}: ${parts.join(', ') || 'no noticeable difference'}`,
      h('span', {class: 'muted'}, ` (from photos ${e.photographs.map((p) => '#' + p).join(', ')})`));
  }
  function stepButton(direction, step, apply) {
    const b = btn(DIRECTION[direction], () => apply(step.apply), 'btn-small');
    if (step.refused) { b.disabled = true; b.setAttribute('title', I18N.tr(step.refused)); return b; }
    const how = step.basis === 'measured' ? `measured from photos ${step.evidence.photographs.map((p) => '#' + p).join(', ')}` : 'based on process experience: not yet measured';
    b.setAttribute('title', `${step.changed.map(changeText).join(', ')} — ${how}`);
    return b;
  }
  /** Describe which scale, power range, or dot settings will be applied. */
  const takeText = (t) => (t.dot_settings ? `Dots: ${setting('power', t.dot_settings.power)}, ${setting('speed', t.dot_settings.speed)}, `
    + `interval ${setting('line_interval', t.dot_settings.line_interval)}${'dot_width' in t ? `, dot correction ${setting('dot_width', t.dot_width)}` : ''}.`
    : `${t.scale ? `Scale ${setting('speed', t.scale.speed)}, interval ${setting('line_interval', t.scale.line_interval)}; ` : ''}`
      + `Min ${setting('min_power', t.min_power)}, Max ${setting('power', t.max_power)}.`);
  /** Describe the proposed plate, its size, and what it will test. */
  function proposalText(p) {
    const changes = p.copies.slice(1).map((c) => c.map(changeText).join(', ')).join('; ');
    const size = p.plate ? ` Plate ${value(p.plate.size_mm[0], 0)} × ${value(p.plate.size_mm[1], 0)} mm: ${copiesOf(p.copies.length)}, each `
      + `${value(p.plate.copy_mm[0], 1)} × ${value(p.plate.copy_mm[1], 1)} mm, each with a grayscale strip below.`
      : ' No image is available for the plate yet. Create the first plate from a photo work or photo zone (Find settings: 8 copies).';
    return `Copy 1 is the baseline; each other copy changes one setting: ${changes}. The photo will show which is best.${size}`;
  }
  const STATUS = {settled: ['search converged', 'ok'], searching: ['search in progress', 'warn'], measured: ['measured, not optimized', 'warn'], unmeasured: ['not measured', 'warn'],
    failed: ['unsuccessful', 'bad']};
  /** Explain why an engraving failed: no visible image or a negative result. */
  const failedWhy = (e) => (e.tone.range_L <= 0
    ? `${e.settings.dither === 'grayscale' ? 'dark areas are no darker than light areas' : `dots are no darker than titanium (L* ${value(e.black_lab[0], 0)})`}: the image is invisible or negative`
    : `image is barely visible: dark areas are darker than light areas by only ${value(e.tone.range_L, 0)} L*`);
  /** Failed engravings for this mode and titanium, newest first. */
  const failedText = (name, failed) => `“${name}” was unsuccessful on this titanium: `
    + failed.slice(0, 3).map((e) => `photo #${e.source.pair_id}, ${setting('power', e.settings.power)} — ${failedWhy(e)}`).join('; ')
    + (failed.length > 3 ? `; plus ${failed.length - 3}` : '') + '.';

  /** Show measured settings, adjustments, and proposed experiments for the current mode. */
  function advisor(path, apply) {
    const el = h('div', {class: 'stack pq-advisor'});
    let shown = null;
    async function load(view) {
      const key = JSON.stringify([view.kind, view.scale, view.min_power, view.max_power, view.dot_power, view.dot_width,
        view.dot_recipe && view.dot_recipe.settings]);
      if (key === shown) return;
      shown = key;
      fill(el, h('p', {class: 'muted small'}, 'Loading knowledge about this mode…'));
      let a;
      try { a = await get(`${path}/advice`); } catch (e) { if (shown === key) fill(el, h('p', {class: 'alert warn small'}, I18N.tr(e.message))); return; }
      if (shown !== key) return;
      const name = PhotoModes.label(a.kind);
      const b = a.best;
      const failed = a.failed || [];
      const status = STATUS[a.status];
      const proposal = a.proposal && (a.proposal.kind === 'next' || a.proposal.plate) ? btn(a.proposal.kind === 'next' ? 'Create next plate' : `Create plate: ${copiesOf(a.proposal.copies.length)}`, async (ev) => {
        const self = ev.currentTarget;
        self.disabled = true;
        try {
          made(a.proposal.kind === 'next' ? await post(`/pairs/${a.proposal.pair_id}/next-variations`, {})
            : await post('/photo-knowledge/plate', {device_id: view.scale.device_id, lens_id: view.scale.lens_id, material_id: view.scale.material_id, kind: a.kind,
              dot_width: a.dot_width}));
        } catch (e) { App.fail(e); self.disabled = false; }
      }, 'btn-small') : null;
      fill(el,
        h('h4', {}, `What is known about “${name}” on this laser and titanium`, status ? [' ', pill(status[0], status[1])] : null),
        b ? h('p', {class: 'small'}, h('strong', {}, a.at_best ? 'Work uses the best measured settings: ' : 'Best measured: '),
          bestText(a.kind, b) + `${b.other_titanium ? ' (on different titanium)' : ''}${b.span_of ? ' — strip range before tone reversal' : ''}.`)
          : failed.length ? null : h('p', {class: 'small muted'}, `This mode has not yet been photographed on this laser and titanium; settings are an estimate.`),
        failed.length ? h('p', {class: 'alert warn small'}, failedText(name, failed), a.stand_in
          ? ` Using the best dark dots from “${PhotoModes.label(a.stand_in.settings.dither)}” on this titanium instead: ${bestText(a.stand_in.settings.dither, a.stand_in)}`
            + `; for “${name}” this remains an estimate until photographed with these dot settings.`
          : ' There are also no dark dots from another mode on this titanium. Dots darker than the titanium are needed; process experience suggests increasing power or decreasing speed or line interval.') : null,
        a.turn && a.turn.past ? h('p', {class: 'alert warn small'}, `Max ${setting('power', a.current.power)} — beyond ${setting('power', a.turn.max_power)}, `
          + 'where this scale’s tones reverse: more power becomes lighter, and dark image areas come out light.') : null,
        a.take ? h('p', {class: 'small'}, btn(a.stand_in ? `Use dark dots from “${PhotoModes.label(a.stand_in.settings.dither)}”`
          : a.turn && a.turn.past && !b ? 'Use range before reversal' : 'Use best settings', () => apply(a.take), 'btn-small'),
          h('span', {class: 'muted'}, ' ' + takeText(a.take))) : null,
        Object.keys(a.effects).length ? h('ul', {class: 'small'}, Object.entries(a.effects).map(([k, e]) => effectLine(k, e))) : null,
        h('div', {class: 'row'}, Object.keys(DIRECTION).map((d) => stepButton(d, a.steps[d], apply))),
        h('p', {class: 'small muted'}, Object.keys(DIRECTION).filter((d) => !a.steps[d].refused).map((d) => `${DIRECTION[d]}: ${a.steps[d].changed.map(changeText).join(', ')}`
          + (a.steps[d].basis === 'measured' ? ' (measured)' : ' (based on process experience)')).join(' · ')),
        a.proposal ? h('p', {class: 'small'}, proposal, h('span', {class: 'muted'}, (a.proposal.kind === 'next'
          ? ` Lab suggestion: the next plate around copy ${a.proposal.best_label}, with half-sized changes. `
          : ` Lab suggestion: the same image around ${a.status === 'unmeasured' || a.status === 'failed' ? 'the best dots from another mode' : 'the best measured result'}. `)
          + proposalText(a.proposal))) : null);
    }
    return {el, load};
  }

  /** Summarize the best measured settings, score, and source photo. */
  const bestText = (kind, b) => `${setting('power', b.settings.power)}${kind === 'grayscale' ? ` (Min ${setting('min_power', b.settings.min_power)})` : ''}, `
    + `${setting('speed', b.settings.speed)}, ${setting('frequency', b.settings.frequency)}, ${setting('pulse_width', b.settings.pulse_width)}, `
    + `interval ${setting('line_interval', b.settings.line_interval)}${b.settings.dot_width != null ? `, dot correction ${setting('dot_width', b.settings.dot_width)}` : ''}`
    + ` — automatic score ${value(b.score, 2)} from photo #${b.source.pair_id}`
    + (b.operator_results && b.operator_results.good ? `; an operator marked the photo engraving successful (${b.operator_results.good})` : '');

  /** Show knowledge and proposed experiments for each photo engraving mode. */
  function kindCards(known, setup) {
    return known.kinds.map((k) => {
      const status = STATUS[k.status];
      const p = k.proposal;
      const make = p && (p.kind === 'next' || p.plate) ? btn(p.kind === 'next' ? 'Create next plate' : `Create plate: ${copiesOf(p.copies.length)}`, async (ev) => {
        const self = ev.currentTarget;
        self.disabled = true;
        try { made(p.kind === 'next' ? await post(`/pairs/${p.pair_id}/next-variations`, {}) : await post('/photo-knowledge/plate', {...setup, kind: k.kind})); }
        catch (e) { App.fail(e); self.disabled = false; }
      }, 'btn-small') : null;
      const why = !p ? (k.status === 'settled' ? 'The search converged: these are the best settings for this mode.' : k.kind === 'grayscale'
        ? 'Start with grayscale scales (Photo engraving → Grayscale scales).' : k.status === 'failed'
          ? 'Dots darker than titanium are needed. Process experience suggests higher power, lower speed, or a smaller line interval.' : 'First photograph any dot photo engraving.')
        : p.kind === 'next' ? `Next plate around copy ${p.best_label}, with half-sized changes.`
          : k.status === 'unmeasured' || k.status === 'failed' ? 'The same image using the best settings from another dot mode.' : 'The same image around the best measured result.';
      return h('article', {class: 'dashboard-insight pq-kind'},
        h('div', {class: 'dashboard-item-top'}, h('strong', {}, PhotoModes.label(k.kind)), status ? pill(status[0], status[1]) : null),
        h('p', {class: 'small'}, k.best ? `Best: ${bestText(k.kind, k.best)}` : k.failed && k.failed.length ? failedText(PhotoModes.label(k.kind), k.failed)
          : 'Not yet photographed on this laser and titanium.'),
        Object.keys(k.effects).length ? h('ul', {class: 'small'}, Object.entries(k.effects).map(([key, e]) => effectLine(key, e))) : null,
        h('p', {class: 'small muted'}, why), p ? h('p', {class: 'small muted'}, proposalText(p)) : null, make);
    });
  }

  return {layerBox, variationsBox, advisor, kindCards, findingLine, effectText, changeText, fromPhoto, recipeFrom, SETTING};
})();
