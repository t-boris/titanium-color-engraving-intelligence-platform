/* Shared photo engraving panels for scales, predictions, coloring, AI, and engraving modes. */
'use strict';
const PhotoPanels = (() => {
  const {h, fill, btn, link, pill, get, post, toast, modal, labText, duration, table, fail} = App;
  const SPREAD_LIMIT = 5;                       // ΔE within which independent engravings agree (agreement.AGREEMENT_DE, DEC-083)
  const BAR_SEGMENTS = 64;                      // segments of the grey -> colour bar (4 grey levels each)
  const TABLE_STEP = 17;                        // the 16 greys of the table: 255, 238, ... 0, the steps of the plate's ramp
  const value = (v, d = 2) => (v == null ? '—' : String(+(+v).toFixed(d)).replace('.', ','));
  const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);
  const materialLabel = (m) => (m ? [m.name, m.grade, m.thickness_mm != null ? `${m.thickness_mm} mm` : null, m.batch].filter(Boolean).join(' · ') : 'titanium unspecified');
  /** Plates of the same grade share a titanium family; a record without a grade stands alone. */
  const titaniumLabel = (sc) => {
    const m = sc.material;
    if (!m || !m.grade) return materialLabel(m);
    const on = ((sc.titanium || {}).measured_on || []).map((t) => t.name);
    return `${m.family && m.family.toLowerCase() !== 'titanium' ? m.family : 'Titanium'} ${m.grade}` + (on.length ? ` · measured on ${on.join(', ')}` : '');
  };
  /** A matching scale uses the same laser, lens, settings, and titanium. */
  const sameScale = (sc, m) => modeQuery({...sc.mode, material_id: null}) === modeQuery({...m, material_id: null})
    && (sc.mode.material_id === m.material_id || ((sc.titanium || {}).records || []).includes(m.material_id));
  const HOW = {'grey ramp': 'gray-scale plate', 'tonal profile': 'photo engraving'};
  const REFERENCE = {chart: ['colors calibrated against reference chart', 'ok'], 'clean titanium': ['camera-relative colors normalized to bare titanium', 'warn'],
    'as photographed': ['camera-relative colors as photographed', 'warn']};

  const settingsText = (m, dpi) => `${value(m.speed, 1)} mm/s · ${value(m.frequency, 1)} kHz · ${m.pulse_width == null ? 'pulse unspecified' : value(m.pulse_width, 0) + ' ns'}`
    + ` · interval ${value(m.line_interval, 4)} mm${dpi ? ` (${dpi} dpi)` : ''} · passes ${m.passes ?? 1}${m.global_passes > 1 ? ` · global ${m.global_passes}×` : ''}`;
  const modeQuery = (m) => new URLSearchParams(Object.entries({device_id: m.device_id, lens_id: App.lensParam(m.lens_id), material_id: m.material_id,
    speed: m.speed, frequency: m.frequency, pulse_width: m.pulse_width, line_interval: m.line_interval, passes: m.passes ?? 1, global_passes: m.global_passes ?? 1})
    .filter(([, v]) => v != null)).toString();
  const GRAYSCALE = 'grayscale';
  const dotted = (v) => !!v.kind && v.kind !== GRAYSCALE;                                    // a dot kind: every dot at one power
  /** Dots using a map recipe fire at its settings rather than the scale settings. */
  const fromMap = (v) => dotted(v) && !!v.dot_recipe;
  /** Settings used for the layer: the dot recipe or the work scale. */
  const firedSettings = (v) => (fromMap(v) ? v.dot_recipe.settings : v.scale);
  const kindName = (key) => { const t = PhotoModes.label(key); return t.charAt(0).toUpperCase() + t.slice(1); };
  const {fromPhoto, recipeFrom} = PhotoQuality;                    // where a recipe's dots come from (BUG-008)
  const greyChip = (level) => h('span', {class: 'sw', style: `background:rgb(${level},${level},${level})`});
  const hexChip = (hex) => (hex ? h('span', {class: 'sw', style: `background:${hex}`}) : h('span', {class: 'sw ge-none', title: 'not measured'}));

  function confirmationPill(c) {
    if (!c || c.median_de == null) return pill(c && c.engravings > 1 ? 'engravings do not overlap in power' : 'one engraving: nothing to compare', 'warn');
    return pill(`${c.confirmed ? 'confirmed' : 'not confirmed'}: median ${value(c.median_de, 1)} ΔE`, c.confirmed ? 'ok' : 'warn');
  }

  const mm = (v) => `${value(v, 1)} mm`;
  const mmList = (list) => list.map((v) => value(v, 1)).join(' and ') + ' mm';

  /** Explain how the scale relates to scan width. */
  function sizeText(size) {
    if (!size) return null;
    if (size.how === 'measured') return {short: `scale measured at width ${mm(size.from_mm[0])}`, tone: 'ok',
      long: `Colors measured at width ${mm(size.from_mm[0])}${size.measured_mm.length > 1 ? ` (scale measured at ${mmList(size.measured_mm)})` : ''}.`};
    if (size.how === 'between') return {short: `${mm(size.row_mm)}: between measurements ${mmList(size.from_mm)}`, tone: 'warn',
      long: `The scale was not measured at ${mm(size.row_mm)}; colors are interpolated between ${mmList(size.from_mm)}. Engrave a sample at this width to check.`};
    if (size.how === 'outside') return {short: `${mm(size.row_mm)}: scale measured at ${mmList(size.measured_mm)}`, tone: 'warn',
      long: `The scale was measured at ${mmList(size.measured_mm)}, not ${mm(size.row_mm)}. Colors use ${mm(size.from_mm[0])} and may differ at this width.`};
    return {short: 'measurement width unknown', tone: 'warn', long: 'The scale measurement width is unknown because its LightBurn files are unavailable.'};
  }
  /** Explain measurement width for a dot recipe from the color map. */
  function recipeSizeText(size) {
    if (!size) return null;
    if (size.how === 'measured') return {short: `color measured at width ${mm(size.from_mm[0])}`, tone: 'ok', long: `Fill color measured at width ${mm(size.from_mm[0])}.`};
    if (size.how === 'between') return {short: `${mm(size.row_mm)}: between measurements ${mmList(size.from_mm)}`, tone: 'warn',
      long: `This color was not measured at ${mm(size.row_mm)}; it is interpolated between ${mmList(size.from_mm)}.`};
    if (size.how === 'outside') return {short: `${mm(size.row_mm)}: color measured at ${mmList(size.measured_mm)}`, tone: 'warn',
      long: `Fill color was measured at ${mmList(size.measured_mm)}, not ${mm(size.row_mm)}. It uses ${mm(size.from_mm[0])} and may differ at this width.`};
    return {short: 'measurement width unknown', tone: 'warn', long: 'The color measurement width is unknown because its LightBurn files are unavailable.'};
  }
  const SIZE_ABOUT = 'Titanium color depends on scan-line length (the image width): the laser returns after each line, '
    + 'and on short lines the titanium has less time to cool.';

  const greySegments = (levels) => Array.from({length: BAR_SEGMENTS}, (_, i) => levels[255 - Math.round(i * 255 / (BAR_SEGMENTS - 1))]);
  /** A selected scale carries the detail response's greys: the card and picture strip then use identical powers, colours and unknowns. */
  function scaleBar(sc) {
    const rows = sc.greys ? greySegments(sc.greys.levels) : sc.bar;
    return h('span', {class: 'ge-bar', role: 'img', 'aria-label': 'Scale colors'}, rows.map((row) => h('span', {
      class: row.hex ? '' : 'ge-none', style: row.hex ? `background:${row.hex}` : '',
      title: `${row.level != null ? `gray ${row.level} · ` : ''}power ${value(row.power)} %${row.hex ? '' : ' · not measured'}`})));
  }

  /** Scale cards use the displayed scan width and, for the selected scale, the current Min/Max. */
  function scaleCard(sc, chosen, choose) {
    const kinds = Object.entries(sc.by_kind).map(([how, n]) => `${HOW[how] || how}: ${n}`).join(' · ');
    const ends = sc.greys ? [sc.greys.levels[255].power, sc.greys.levels[0].power] : sc.span;
    const size = sizeText(sc.size);
    return h('button', {type: 'button', class: 'ge-scale' + (chosen ? ' is-chosen' : ''), 'aria-pressed': String(chosen), onClick: choose},
      scaleBar(sc),
      h('span', {class: 'ge-ends small'}, h('span', {}, `P ${value(ends[0], 1)} %`), h('span', {}, `P ${value(ends[1], 1)} %`)),
      sc.size && sc.size.row_mm != null ? h('span', {class: 'small muted', title: size ? size.long : ''},
        `Colors at width ${mm(sc.size.row_mm)}`,
        sc.size.how === 'outside' ? ` · from measurement at ${mmList(sc.size.from_mm)}` : '') : null,
      h('strong', {}, settingsText(sc.mode, sc.dpi)),
      sc.results && sc.results.total ? h('span', {class: 'small ge-result-summary'}, `Photos: good ${sc.results.good} · bad ${sc.results.bad} · unrated ${sc.results.unrated}`) : null,
      sc.examples && sc.examples.length ? h('span', {class: 'ge-scale-examples'}, sc.examples.slice(0, 3).map((r) => h('span', {class: 'small'},
        r.photo ? h('img', {src: r.photo, loading: 'lazy', alt: `Engraving photo: ${r.title}`}) : null,
        `${r.title} · ${r.layer} · photo: ${{good: 'good', bad: 'bad', unrated: 'unrated'}[r.verdict]}; color: ${{good: 'good', bad: 'bad', unrated: 'unrated'}[((r.assessments || {}).colour || {}).verdict || 'unrated']}`))) : null,
      h('span', {class: 'small muted'}, `${titaniumLabel(sc)} · ${kinds} · ${value(sc.time_s_per_cm2, 0)} s/cm²`),
      sc.sizes && sc.sizes.length ? h('span', {class: 'small muted'}, `measured at widths ${mmList(sc.sizes.map((z) => z.row_mm))}`) : null,
      h('span', {class: 'row'}, confirmationPill(sc.confirmation), pill(...(REFERENCE[sc.reference] || [sc.reference]))));
  }

  /** Color strip for grayscale or selectable dot power. */
  function greyBar(levels, dot = null) {
    const segments = greySegments(levels);
    const lo = levels[255].power, hi = levels[0].power;
    const strip = h('div', {class: 'ge-strip' + (dot ? ' ge-pickable' : ''), 'aria-label': dot ? 'Dot color at each power: click to select' : 'Color of each gray'},
      segments.map((row) => h('span', {class: row.hex ? '' : 'ge-none', style: row.hex ? `background:${row.hex}` : '',
        title: dot ? `power ${value(row.power)} %${row.hex ? '' : ' · not measured'}` : `gray ${row.level} · power ${value(row.power)} %${row.hex ? '' : ' · not measured'}`})));
    if (!dot) {
      return h('div', {class: 'stack ge-greybar'}, strip, h('div', {class: 'ge-strip ge-ramp', 'aria-hidden': 'true'}),
        h('div', {class: 'ge-ends small'}, h('span', {}, `white 255 · Min ${value(lo, 1)} %`), h('span', {}, `black 0 · Max ${value(hi, 1)} %`)));
    }
    strip.addEventListener('click', (ev) => {
      const box = strip.getBoundingClientRect();
      if (!(box.width > 0)) return;
      const share = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
      dot.pick(Math.round((lo + share * (hi - lo)) * 10) / 10);
    });
    const onScale = dot.power != null;
    const mark = onScale ? h('span', {class: 'ge-dotmark', 'aria-hidden': 'true', style: `left:${hi > lo ? Math.min(100, Math.max(0, (dot.power - lo) / (hi - lo) * 100)) : 0}%`}) : null;
    return h('div', {class: 'stack ge-greybar'}, h('div', {class: 'ge-markbox'}, strip, mark),
      h('div', {class: 'ge-ends small'}, h('span', {}, `${value(lo, 1)} %`), h('span', {}, onScale ? `dots: ${value(dot.power, 1)} %` : `dots — ${dot.from || 'from color map'}`),
        h('span', {}, `${value(hi, 1)} %`)));
  }

  // L, a and b each stay whole: a narrow column breaks the colour only between them
  const labLines = (lab) => labText(lab).replace(/ (?!·)(?<!· )/g, '\u00a0');

  function greyTable(levels) {
    const rows = [];
    for (let level = 255; level >= 0; level -= TABLE_STEP) {
      const r = levels[level];
      rows.push([h('span', {class: 'ge-nowrap'}, greyChip(level), ` ${level}`), value(r.power), r.lab ? h('span', {class: 'ge-lab'}, hexChip(r.hex), ' ', labLines(r.lab)) : h('span', {class: 'muted'}, 'outside measured powers'),
        r.spread_de == null ? h('span', {class: 'muted'}, '—') : pill(`${value(r.spread_de, 1)} ΔE`, r.spread_de > SPREAD_LIMIT ? 'warn' : 'ok')]);
    }
    return table(['Image gray (0–255)', 'Power, %', 'Color on titanium', 'Engraving difference'], rows, '', true);
  }

  const sourceText = (s) => [s.title, HOW[s.how] || s.how, s.layer_name, s.photo ? `photo ${s.photo}` : null].filter(Boolean).join(' · ');

  /** One scale engraving per row. */
  function confirmationBlock(c) {
    const rows = c.rows.map((r) => h('li', {class: 'ge-entry'},
      h('div', {class: 'ge-entry-head'}, h('span', {}, link('/experiment/' + encodeURIComponent(r.engraving.experiment), r.engraving.title), ` · ${HOW[r.engraving.how] || r.engraving.how}`),
        r.median_de == null ? null : pill(`median ${value(r.median_de, 1)} ΔE`, r.median_de > c.tolerance_de ? 'warn' : 'ok')),
      h('div', {class: 'small muted'}, [`points ${r.points}`, r.compared ? `compared ${r.compared}` : 'nothing to compare',
        r.max_de == null ? null : `maximum ${value(r.max_de, 1)} ΔE`, r.within == null ? null : `within ${c.tolerance_de} ΔE: ${value(r.within * 100, 0)} %`].filter(Boolean).join(' · '))));
    return h('div', {class: 'stack'}, h('h4', {}, 'Do experiments confirm the scale?'),
      h('p', {class: 'small'}, 'Each engraving is compared at its powers with the scale built from all others. Confirmed if the median difference is at most '
        + `${c.tolerance_de} ΔE. `, confirmationPill(c)),
      rows.length ? h('ul', {class: 'ge-entries'}, rows) : h('p', {class: 'muted'}, 'No engravings'));
  }

  function fillsBlock(fills) {
    if (!fills.length) return null;
    return h('details', {}, h('summary', {}, `Fills with the same settings (${fills.length}) — for comparison, excluded from the scale`),
      h('p', {class: 'small muted'}, 'Fill and an image gray at the same power produce different colors (up to 36 ΔE in your light and mid tones), so the scale uses only photo engravings and gray-scale plates.'),
      table(['Power, %', 'Fill color', 'Difference from scale', 'Where'], fills.map((f) => [value(f.power), h('span', {class: 'ge-lab'}, hexChip(f.hex), ' ', labLines(f.lab)),
        f.de == null ? h('span', {class: 'muted'}, f.curve_lab ? 'different measurement method' : 'outside scale') : pill(`${value(f.de, 1)} ΔE`, f.de > SPREAD_LIMIT ? 'warn' : 'ok'),
        sourceText(f.source)]), '', true));
  }

  function pointsBlock(curve) {
    return h('details', {}, h('summary', {}, `Measured scale points (${curve.points.length})`),
      table(['Power, %', 'Color', 'Engravings', 'Where measured'], curve.points.map((p) => [value(p.power), h('span', {class: 'ge-lab'}, hexChip(p.hex), ' ', labLines(p.lab)), String(p.engravings),
        h('div', {class: 'stack small'}, p.sources.map((s) => h('span', {}, link('/experiment/' + encodeURIComponent(s.experiment), s.title), ` · ${HOW[s.how] || s.how}`,
          s.gray != null ? ` · gray ${Math.round(s.gray * 255)}` : '', s.pair_id ? [' · ', link(`/analysis/${s.pair_id}`, 'analysis')] : null)))]), '', true));
  }

  const newSlots = () => ({title: h('span', {class: 'sub ge-settings'}), powers: h('div', {class: 'ge-powers'}), error: h('div'), bar: h('div', {class: 'ge-barbox'}),
    scale: h('div', {class: 'stack'}), confirm: h('div', {class: 'stack'}), points: h('div', {class: 'stack'})});

  /** Empty the scale slots and show a message. */
  function emptySlots(slots, text) {
    fill(slots.title);
    slots.title.setAttribute('title', '');
    fill(slots.powers);
    fill(slots.error);
    for (const place of [slots.bar, slots.scale, slots.confirm, slots.points]) fill(place, h('p', {class: 'muted'}, text));
  }

  /** Draw scale details, powers, measured widths, and optional dot selection. */
  function scaleDetail(sc, slots, {initial = null, changed = null, rowMm = null, dot = null, loaded = null} = {}) {
    let span = sc.span;
    let timer = null, seq = 0, stopped = false;
    let atMm = rowMm != null ? rowMm : (sc.size ? sc.size.row_mm : null);
    const widths = rowMm == null && sc.sizes && sc.sizes.length > 1 ? h('div', {class: 'row ge-sizes', role: 'group', 'aria-label': 'Width for displayed colors'},
      h('span', {class: 'small'}, 'Width:'), sc.sizes.map((z) => h('button', {type: 'button', class: 'btn btn-small', 'aria-pressed': String(z.row_mm === atMm),
        title: `measured engravings: ${z.engravings}, points: ${z.points}`, onClick: (ev) => {
          const self = ev.currentTarget;
          atMm = z.row_mm;
          for (const b of self.parentNode.querySelectorAll('button')) b.setAttribute('aria-pressed', String(b === self));
          load(false);
        }}, mm(z.row_mm)))) : null;
    // the ends of the two powers are 0 to 100 % (prediction_store.check_power_range); the dots' power must lie inside the powers the scale was measured at,
    // at this width (photo_zones.change), which the scale says (``span``): its rule is read again whenever the scale says another span
    const dotRule = {...Forms.QUANTITIES.photoPower, label: 'Dot power', min: span ? span[0] : 0, max: span ? span[1] : 100, source: 'photo_zones.change (the measured span)'};
    const slider = (label, short, start, moved = () => schedule(), rule = Forms.QUANTITIES.photoPower) => {
      const range = h('input', {type: 'range', min: rule.min, max: rule.max, step: 0.1, value: start, 'aria-label': label});
      const exact = h('input', {type: 'number', min: rule.min, max: rule.max, step: 'any', value: start, 'aria-label': label});
      bindSlider(range, () => { exact.value = range.value; exact.removeAttribute('aria-invalid'); note.textContent = ''; }, moved,
        (active) => { if (active) { ++seq; clearTimeout(timer); } });
      if (rule === Forms.QUANTITIES.photoPower) exact.addEventListener('input', () => { ++seq; clearTimeout(timer); });
      // a value outside is kept in the box with the reason beside it and is not applied
      // (a wrong value goes on to the owner's save as well: its tracker then says «not saved» with what was typed, and the server gives its reason)
      const note = Forms.watch(exact, rule, (v) => { range.value = v; moved(); }, {wrong: () => moved()});
      const notes = [Forms.describe(range, rule), Forms.describe(exact, rule)];
      return {exact, range, note, notes, rule, box: h('label', {class: 'ge-power', title: label}, h('span', {class: 'small'}, short), range, exact, ...notes)};
    };
    const measured = [Math.ceil(span[0] * 10 - 1e-9) / 10, Math.floor(span[1] * 10 + 1e-9) / 10];
    const [lo0, hi0] = dot ? measured : initial || measured;
    const low = slider('Min power, % (white)', 'Min, %', lo0);
    const high = slider('Max power, % (black)', 'Max, %', hi0);
    let levelsShown = null;
    const dotPower = dot ? slider('Dot power, %', 'Dots, %', dot.power, () => { clearTimeout(timer); timer = setTimeout(() => pickDot(+dotPower.exact.value), 250); }, dotRule) : null;
    const dotSource = dot && (dot.map || dot.recipe) ? dotSourceBox(dot, () => pickDot(dot.power)) : null;
    /** Update dot power immediately; the server validates the measured range. */
    function pickDot(p) {
      if (!(p >= 0 && p <= 100)) return;
      dotPower.exact.value = String(p);
      dotPower.range.value = String(p);
      dot.power = p;
      dot.recipe = null;
      if (levelsShown) fill(slots.bar, greyBar(levelsShown, {power: p, pick: pickDot}));
      dot.changed(p);
    }
    const dotBar = () => ({power: dot.recipe ? null : dot.power, pick: pickDot, from: dot.recipe ? recipeFrom(dot.recipe) : null});
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const loading = () => h('p', {class: 'muted'}, 'Loading scale…');
    const onMap = dot && dot.recipe ? ` · dots use settings ${fromPhoto(dot.recipe) ? `of dots ${recipeFrom(dot.recipe)}` : 'of the color map recipe'}` : '';      // the scale stays the work's; its dots fire elsewhere
    fill(slots.title, (onMap ? 'scale: ' : '') + settingsText(sc.mode, sc.dpi) + onMap);
    slots.title.setAttribute('title', `${settingsText(sc.mode, sc.dpi)} · ${titaniumLabel(sc)}${onMap}`);
    fill(slots.powers, ...(dot ? [dot.recipe ? null : dotPower.box, dotPower.note, dotSource] : [low.box, low.note, high.box, high.note]), widths);
    fill(slots.error, error);
    fill(slots.bar, loading());
    for (const tab of [slots.scale, slots.confirm, slots.points]) fill(tab, loading());
    async function load(byOperator) {
      const lo = +low.exact.value, hi = +high.exact.value;
      error.hidden = true;
      if (![low, high].every((b) => Forms.readNumber(b.exact, Forms.QUANTITIES.photoPower, {required: true}).ok)) {
        if (byOperator && changed) changed(lo, hi);                       // the owner's tracker is told what is on the screen; the scale is not asked for it
        return;                                                           // the reason stands beside the box that is wrong
      }
      if (!(lo <= hi)) { error.textContent = 'Min power must not exceed Max.'; error.hidden = false; return; }
      if (byOperator && changed) changed(lo, hi);
      const mine = ++seq;
      try {
        const d = await get(`/grey-scales/scale?${modeQuery(sc.mode)}&min_power=${lo}&max_power=${hi}${atMm != null ? `&row_mm=${atMm}` : ''}`);
        if (stopped || mine !== seq) return;
        span = d.span;
        if (dotPower && span) {                                           // the scale's span at this width is the rule of the dots' power
          Object.assign(dotRule, {min: span[0], max: span[1]});
          for (const part of [dotPower.range, dotPower.exact]) { part.setAttribute('min', String(span[0])); part.setAttribute('max', String(span[1])); }
          for (const note of dotPower.notes) note.textContent = Forms.rulesText(dotRule);
        }
        const size = sizeText(d.size);
        const levels = d.greys.levels;
        const unmeasured = 256 - d.greys.measured_levels;
        levelsShown = levels;
        fill(slots.bar, greyBar(levels, dot ? dotBar() : null));
        fill(slots.scale,
          h('p', {class: 'small muted'}, `${titaniumLabel(sc)}. Measured from ${value(span[0], 1)} to ${value(span[1], 1)}%. Image gray maps linearly to power: `
            + 'white (255) is Min, black (0) is Max. Color is interpolated in Lab between measured powers; outside them it is not predicted.'),
          unmeasured ? h('p', {class: 'small muted'}, `Grays outside measured powers (${value(span[0], 1)}–${value(span[1], 1)}%): ${unmeasured} of 256 are hatched; color is not predicted there.`) : null,
          size ? h('p', {class: 'small'}, pill(size.short, size.tone), ' ', size.long, h('span', {class: 'muted'}, ' ' + SIZE_ABOUT)) : null,
          d.examples && d.examples.length ? resultCards(d.examples, () => load(false)) : null,
          greyTable(levels), h('ul', {class: 'small'}, d.notes.map((n) => h('li', {}, I18N.tr(n)))));
        fill(slots.confirm, confirmationBlock(d.confirmation));
        fill(slots.points, fillsBlock(d.fill_points), pointsBlock(d.curve));
        if (loaded) loaded(d);
      } catch (e) { if (!stopped && mine === seq) { error.textContent = e.message; error.hidden = false; } }
    }
    function schedule() { ++seq; clearTimeout(timer); timer = setTimeout(() => load(true), 250); }
    load(false);
    return {stop() { stopped = true; clearTimeout(timer); }};
  }

  /** Actual photo layers and numbered exports, with operator judgements independent of the automatic tonal score. */
  function resultCards(rows, changed) {
    const labels = {good: ['Good', 'ok'], bad: ['Bad', 'bad'], unrated: ['Unrated', 'warn']};
    const cards = rows.map((row) => {
      function assessment(aspect, label) {
        const current = (row.assessments || {})[aspect] || {verdict: aspect === 'photo' ? row.verdict || 'unrated' : 'unrated', note: ''};
        const status = pill(...labels[current.verdict]);
        const verdict = h('select', {'aria-label': `${label}: ${row.layer} · ${row.title}`}, Object.entries(labels).map(([key, v]) => h('option', {value: key}, v[0])));
        verdict.value = current.verdict;
        // photo_results.mark: the note is at most 1000 characters once trimmed; a longer one is refused with its length, not cut at 1000 as it is pasted
        const form = Forms.create();
        const noteBox = h('textarea', {rows: 2, placeholder: 'What happened on this marker…'});
        noteBox.value = current.note || '';
        const note = form.add('note', 'Comment', noteBox, {maxLength: 1000, empty: ''});
        const save = btn(`Save: ${label.toLowerCase()}`, async () => {
          const v = form.collect();
          if (!v) return;
          save.disabled = true;
          try {
            const saved = await post('/photo-results/mark', {source: row.source, aspect, verdict: verdict.value, note: v.note});
            if (changed) await changed(saved);
            else { status.textContent = labels[saved.verdict][0]; status.className = `pill ${labels[saved.verdict][1]}`; }
          } catch (e) { form.fail(e); }
          finally { save.disabled = false; }
        }, 'btn-small');
        return h('div', {class: 'stack ge-assessment', 'data-aspect': aspect, role: 'group', 'aria-label': `${label}: ${row.layer} · ${row.title}`},
          h('div', {class: 'row'}, h('strong', {}, label), status, verdict, save), note, form.error);
      }
      const p = row.settings;
      return h('article', {class: 'ge-result stack'}, h('div', {class: 'row'}, h('strong', {}, `Marker ${row.layer}`), link(row.url.replace(/^#/, ''), row.title),
        h('span', {class: 'small muted'}, when(row.at))),
        row.photo ? h('a', {href: row.url}, h('img', {class: 'ge-result-photo', src: row.photo, loading: 'lazy', alt: `Engraving photo ${row.title}`}))
          : h('p', {class: 'small muted'}, 'No photo added. The assessment is based on the operator’s report.'),
        h('p', {class: 'small'}, `Min ${value(p.min_power, 1)} / Max ${value(p.power, 1)} % · ${settingsText(p)}${row.width_mm != null ? ` · width ${mm(row.width_mm)}` : ''}`),
        assessment('colour', 'Color'), assessment('photo', 'Photo engraving'));
    });
    return h('section', {class: 'ge-results stack'}, h('h4', {}, 'Results by LightBurn marker'),
      h('p', {class: 'small muted'}, 'Color and photo engraving are assessed separately for this layer and file version. Unsuccessful measurements are retained.'), cards);
  }

  function exportedResults(planId, zone = null) {
    const el = h('section', {class: 'stack'});
    async function load() {
      try {
        const data = await get(`/photo-results/work/${planId}${zone != null ? `?zone=${zone}` : ''}`);
        fill(el, data.results.length ? resultCards(data.results, load) : h('p', {class: 'small muted'}, 'Export a LightBurn file first; assessments are linked to its version.'));
      } catch (e) { fill(el, h('p', {class: 'small muted'}, e.message)); }
    }
    load();
    return el;
  }

  /** Choose dot color from the map or return to the scale at the same power. */
  function dotSourceBox(dot, back) {
    const toMap = (label) => (dot.map ? btn(label, () => dot.map(), 'btn-small') : null);
    if (!dot.recipe) {
      const b = toMap('Color from map');
      b.setAttribute('title', 'Open the color map to select a measured dot color; dots use that color’s settings');
      return h('div', {class: 'row ge-dotsource'}, b);
    }
    const r = dot.recipe;
    return h('div', {class: 'row ge-dotsource ge-dotsource-map'}, h('span', {class: 'small'}, 'Dots'), hexChip(dot.hex),
      h('span', {class: 'small'}, `${recipeFrom(r)}: ${value(r.settings.power, 1)} % · ${settingsText(r.settings, dot.dpi)}`),
      r.missing ? pill('color is no longer measured', 'warn') : null,
      toMap('Another color'), btn('Back to scale', back, 'btn-small'));
  }

  // ---- work ------------------------------------------------------------------------------------------------------------------------

  /** Offer a width-matched gray-ramp plate. */
  function rampOffer(view, size, path) {
    const dots = dotted(view);
    const make = btn(dots ? 'Test this mode' : 'Test at work width', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      const end = App.landing(self);
      try {
        const made = await post(path, {});
        if (end.stillHere()) toast(`Created: ${made.name}`, 'ok');
        end.go('/experiment/plan-' + made.plan_id, {title: 'Plate created', message: `Created: ${made.name}. Open the experiment, engrave the plate, photograph it, and upload the photo.`, openLabel: 'Open plate', goOptions: {}});
      } catch (e) { fail(e); self.disabled = false; }
    }, (dots ? view.picture && !view.picture.estimate : size && size.how === 'measured') ? 'btn-small' : 'primary btn-small');
    if (dots) {
      const corrected = view.dot_width != null ? `, with dot-width adjustment ${value(view.dot_width, 3)} mm` : '';
      const at = fromMap(view) ? `using ${fromPhoto(view.dot_recipe) ? `dot settings ${recipeFrom(view.dot_recipe)}` : 'color-map settings'} (${settingsText(view.dot_recipe.settings)}, ${value(view.dot_recipe.settings.power, 1)} %)${corrected}`
        : `at dot power ${value(view.dot_power, 1)}%${corrected} and the scale settings`;
      return h('p', {class: 'small'}, make, h('span', {class: 'muted'}, ` A plate with one gray strip ${mm(view.width_mm)} wide in “${kindName(view.kind)}” mode, `
        + `${at}. Engrave, photograph, and upload it to measure this mode at these settings and show measured tones instead of an estimate.`));
    }
    return h('p', {class: 'small'}, make, h('span', {class: 'muted'}, ` A plate with one gray strip ${mm(view.width_mm)} wide using the scale settings, `
      + `Min ${value(view.min_power, 1)}% and Max ${value(view.max_power, 1)}%. Engrave, photograph, and upload it to measure the scale at the work width.`));
  }

  /** “Find settings” (feature photo-engraving-quality, REQ-002): a plate of eight copies of a part of the picture, the first at the
      work's settings and every other with one setting changed, a grey ramp at the same settings under each; ``path`` is where to ask for it.
      Its photograph shows which setting makes the picture darker, lighter, sharper or softer, and which copy is best. */
  function variationsOffer(view, path) {
    const dots = dotted(view);
    const make = btn('Find settings: 8 copies', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      const end = App.landing(self);
      try {
        const made = await post(path, {});
        if (end.stillHere()) toast(`Created: ${made.name}`, 'ok');
        end.go('/experiment/plan-' + made.plan_id, {title: 'Plate created', message: `Created: ${made.name}. Open the experiment, engrave the plate, photograph it, and upload the photo.`, openLabel: 'Open plate', goOptions: {}});
      } catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    const changes = dots
      ? 'power −20% and +20%, speed +40%, line interval ×1.69, dot-width adjustment on/off, and two other dot modes'
      : 'Max −20% and +20%, Min ±3, line interval ×1.5 and ×0.75, speed ×0.7 and ×1.4';
    return h('p', {class: 'small ge-variations'}, make, h('span', {class: 'muted'}, ' Plate: the image area with the richest tones at its actual size — '
      + `eight copies. The first uses the work settings; each other copy changes one setting: ${changes}. Each copy has a gray strip with the same `
      + 'settings. Engrave, photograph, and upload it to see which changes make the image darker, lighter, sharper, or softer.'));
  }

  const CHOICES = [['drawing', 'Preserve image'], ['nearest', 'Nearest color'], ['objects', 'Color by object']];
  const CHOICE_ABOUT = '“Preserve image” maps image tones along a smooth scale from lightest to darkest. Neighboring tones receive neighboring powers, '
    + 'keeping skin gradients smooth. JPEG grain and blocks are smoothed (up to 0.25 mm), lips, eyes, and facial shadows emphasized (up to 1.5 mm), '
    + 'and midtones lightened. Image hues are not reproduced. “Nearest color” selects the gray with the closest scale color, even when much lighter or darker. '
    + '“Color by object” preserves the image except for objects assigned their own color on the Coloring tab.';
  const CONTOURS_ABOUT = 'Only when matching grays to colors: image boundaries that would be lost on titanium are outlined with a 0.3 mm line, '
    + 'using the darkest scale gray, or the lightest on dark areas or bright highlights. Areas using “One tone” are not outlined.';

  /** Describe how well grayscale matching preserves the image or matches colors. */
  function matchText(match) {
    if (!match) return null;
    if (match.manually_adjusted) return h('p', {class: 'small'}, 'Grays were adjusted manually after matching. The preview and file use these changes; automatic matching metrics do not apply to them.');
    const used = `grays used: ${match.greys_used} of ${match.greys_available}`;
    if (match.choice === 'objects') {
      const done = match.objects || [];
      return h('p', {}, h('strong', {}, 'Color by object: '), done.length
        ? h('span', {}, `${done.length} ${done.length === 1 ? 'object' : 'objects'} in assigned colors — `,
          ...done.flatMap((o, i) => [i ? ', ' : '', hexChip(o.hex), objectName(o.key)]),
          `; the rest uses “Preserve image”. Light-dark order matches the image${match.order == null ? '' : ` by ${value(match.order * 100, 0)}%`}; ${used}.`)
        : 'no objects have assigned colors yet; the whole image uses “Preserve image”. Assign object colors on the Coloring tab.');
    }
    if (match.choice === 'nearest') {
      return h('p', {}, h('strong', {}, 'Color matching: '), `nearest scale colors differ from the image colors by a median ${value(match.median_de, 1)} ΔE `
        + `(90% of pixels within ${value(match.p90_de, 1)}); ${used}.`);
    }
    return h('p', {}, h('strong', {}, 'Image preserved: '), `image tones use a smooth scale path of ${match.path} grays `
      + `(L* ${value(match.reach[1], 0)} to ${value(match.reach[0], 0)})${match.order == null ? '' : `, with light-dark order matching the image `
      + `by ${value(match.order * 100, 0)}%`}; image hues are not reproduced (median ${value(match.median_de, 1)} ΔE from its colors); ${used}.`);
  }

  /** Describe whether outlines are used and how much of the image they cover. */
  function contoursText(view, info) {
    if (!view.by_colour) return null;
    if (!view.contours) return h('p', {class: 'small muted'}, 'Outlines are off: boundaries that would be lost on titanium are not outlined.');
    const share = info.contours_report ? info.contours_report.share : 0;
    return h('p', {class: 'small'}, h('strong', {}, 'Outlines: '), share > 0
      ? `boundaries that would be lost on titanium are outlined with a 0.3 mm line — ${value(share * 100, share < 0.001 ? 2 : 1)}% of the image.`
      : 'no image boundaries would be lost on titanium; nothing to outline.');
  }

  const TONE = {brightness: 0, contrast: 0, gamma: 1};          // the picture's greys as they are (photo_state.TONE)
  const TONE_ABOUT = 'Brightness, contrast and gamma are applied before the image becomes laser power or dots. The prediction and LightBurn file use the same image; '
    + 'LightBurn retains its default adjustments (0 / 0 / 1). Brightness shifts all tones, contrast separates light and dark, and gamma changes the midtones. '
    + 'Gamma below 1 lightens midtones; above 1 darkens them. In dot modes, lighter areas contain fewer dots.';
  const TONE_MATCHED = 'Adjustments are applied after grayscale matching and included in the LightBurn file. Darker gray means higher power. '
    + 'Titanium color and lightness follow the measured scale, so more power does not always darken the metal.';

  /** Image adjustment sliders save after a pause and retain their values while a change is in flight. */
  // A drag or held adjustment key is one change, even when it lasts longer than the save debounce.
  function bindSlider(range, update, commit, start = () => {}) {
    let active = false, dirty = false;
    const keys = new Set(['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'Home', 'End']);
    const begin = () => { if (!active) { active = true; dirty = false; start(true); } };
    const finish = () => { if (!active) return; active = false; start(false); if (dirty) commit(); dirty = false; };
    range.addEventListener('pointerdown', (ev) => { begin(); if (range.setPointerCapture && ev.pointerId != null) range.setPointerCapture(ev.pointerId); });
    range.addEventListener('pointerup', finish);
    range.addEventListener('pointercancel', finish);
    range.addEventListener('keydown', (ev) => { if (keys.has(ev.key)) begin(); });
    range.addEventListener('keyup', (ev) => { if (keys.has(ev.key)) finish(); });
    range.addEventListener('blur', finish);
    range.addEventListener('input', () => { update(); if (active) dirty = true; else commit(); });
  }

  function toneSliders(save) {
    let timer = null, busy = 0, last = null;
    let adjusting = false;
    const defaults = {...TONE, sharpness: 0};
    // the limits are the server's (photo_state.TONE_LIMITS and the sharpness check); the slider has the step, the box the exact value
    const QUANTITY = {brightness: 'toneBrightness', contrast: 'toneContrast', gamma: 'toneGamma', sharpness: 'sharpness'};
    const one = (key, label, about, short, step) => {
      const q = Forms.QUANTITIES[QUANTITY[key]];
      const range = h('input', {type: 'range', min: q.min, max: q.max, step, value: defaults[key], 'aria-label': label});
      const exact = h('input', {type: 'number', min: q.min, max: q.max, step: 'any', value: defaults[key], 'aria-label': label});
      bindSlider(range, () => { exact.value = range.value; exact.removeAttribute('aria-invalid'); note.textContent = ''; }, later,
        (active) => { adjusting = active; if (active) { clearTimeout(timer); timer = null; } });
      const note = Forms.watch(exact, QUANTITY[key], (v) => { range.value = v; later(); }, {wrong: () => later()});
      // the name is the name; the unit, the permitted values and what the number does are read after it
      return {key, range, exact, note, box: h('label', {class: 'ge-power', title: `${label}: ${about}`}, h('span', {class: 'small'}, short), range, exact,
        Forms.describe(range, q, {extra: about}), Forms.describe(exact, q, {extra: about}))};
    };
    const all = [one('brightness', 'Image brightness, %', 'below zero darkens; above zero lightens', 'Brightness', 1),
      one('contrast', 'Image contrast, %', 'above zero increases the difference between light and dark', 'Contrast', 1),
      one('gamma', 'Image gamma', 'below 1 lightens midtones; above 1 darkens them', 'Gamma', 0.05),
      one('sharpness', 'Image sharpness', 'enhances fine detail; 0 means no additional sharpening', 'Sharpness', 1)];
    const toneOf = (view) => ({...defaults, ...(view.tone || {}), sharpness: view.sharpness || 0});
    const set = (tone) => { for (const s of all) { s.range.value = String(tone[s.key]); s.exact.value = String(tone[s.key]); s.exact.removeAttribute('aria-invalid'); s.note.textContent = ''; } };
    async function send(values) {
      busy += 1;
      const change = {tone: Object.fromEntries(Object.keys(TONE).map((k) => [k, values[k]]))};
      if (values.sharpness !== ((last && last.sharpness) || 0)) change.sharpness = values.sharpness;
      await save(change);
      busy -= 1;
      if (!busy && !timer && last) set(toneOf(last));
    }
    function later() {
      clearTimeout(timer);
      timer = setTimeout(() => {
        timer = null;
        send(Object.fromEntries(all.map((s) => [s.key, +s.exact.value])));      // a wrong box is sent as typed: the owner's tracker keeps it and the server refuses it
      }, 300);
    }
    const reset = btn('Reset adjustments', () => { clearTimeout(timer); timer = null; set(defaults); send({...defaults}); }, 'btn-small');
    reset.setAttribute('title', 'Brightness 0, contrast 0, gamma 1, sharpness 0: no manual adjustments');
    const note = h('p', {class: 'small muted ge-tone-note', hidden: true}, TONE_MATCHED);
    const gamma = all.find((s) => s.key === 'gamma');
    const el = h('div', {class: 'ge-powers ge-tone', role: 'group', 'aria-label': 'Image adjustments', title: TONE_ABOUT},
      all.filter((s) => s.key !== 'gamma').map((s) => [s.box, s.note]),
      h('details', {class: 'ge-gamma-calibration'}, h('summary', {}, 'Gamma calibration'),
        h('p', {class: 'small muted'}, 'Gamma adjusts midtones while leaving black and white unchanged.'), gamma.box, gamma.note),
      h('div', {class: 'row'}, reset), note);
    function show(view) {
      last = view;
      el.hidden = !!view.problem;
      const tone = toneOf(view), matched = !dotted(view) && !!view.by_colour;
      if (!timer && !busy && !adjusting) set(tone);
      reset.disabled = all.every((s) => tone[s.key] === defaults[s.key]);
      note.hidden = !matched;
    }
    return {el, show};
  }

  /** Render the work image, prediction, calibration controls, and detailed engraving settings. */
  function calibrationControls(powers, dotWidth = null) {
    return h('details', {class: 'ge-calibration'}, h('summary', {}, 'Power and dot calibration'),
      h('p', {class: 'small muted'}, 'Min and Max map image tones to laser power. Dot correction adjusts the modeled dot width; measured-range limits still apply.'),
      powers, dotWidth);
  }

  function workPicture(save, chooseKind, {ramp = null, variations = null, advice = null, original = null, width: widthFree = true, objects = true, layer = null, stage = null} = {}) {
    const previousImage = h('img', {class: 'ge-previous-image', alt: 'Prediction immediately before the latest change'});
    const comparisonError = h('p', {class: 'small alert warn', role: 'status', hidden: true}, 'The previous prediction is no longer available.');
    const comparison = h('details', {class: 'ge-comparison', hidden: true},
      h('summary', {}, 'Compare with previous change'),
      h('p', {class: 'small muted'}, 'This prediction shows the settings immediately before the latest change.'), previousImage,
      comparisonError);
    previousImage.addEventListener('error', () => { comparisonError.hidden = false; previousImage.hidden = true; });
    function compare(previous, next) {
      const before = previous && previous.picture && previous.picture.preview;
      const after = next && next.picture && next.picture.preview;
      comparison.hidden = !(before && after);
      if (!before || !after) { comparison.open = false; return; }
      comparisonError.hidden = true;
      previousImage.hidden = false;
      previousImage.setAttribute('src', before);
    }
    const kind = btn('Mode: grayscale', () => chooseKind(), 'btn-small');
    kind.setAttribute('title', 'Choose grayscale or a dot engraving mode, each with a preview');
    const width = h('input', {type: 'number', min: '1', max: '1000', step: 'any', 'aria-label': 'Width on titanium, mm', style: 'width:6em', disabled: !widthFree,
      title: widthFree ? null : 'Zone width follows its areas; image lines span the zone'});
    const byColour = h('input', {type: 'checkbox'});
    const choice = h('select', {'aria-label': 'How to match grayscale', title: CHOICE_ABOUT}, CHOICES.filter(([v]) => objects || v !== 'objects').map(([v, t]) => h('option', {value: v}, t)));
    const contours = h('input', {type: 'checkbox', 'aria-label': 'Contours'});
    const out = h('div', {class: 'ge-stage'});
    const foot = h('div', {class: 'ge-foot'});
    const details = h('div', {class: 'stack'});
    // prediction_store.check_width: 1 to 1000 mm; a width outside is kept in the box with the reason beside it and is not saved
    const widthNote = Forms.watch(width, 'pictureWidth', (v) => save({width_mm: v}), {wrong: () => save({width_mm: +width.value})});
    byColour.addEventListener('change', () => save({by_colour: byColour.checked}));
    choice.addEventListener('change', () => save({colour_choice: choice.value}));
    contours.addEventListener('change', () => save({contours: contours.checked}));
    const predictionStatus = h('p', {class: 'small ge-prediction-status', role: 'status', 'aria-live': 'polite'});
    function showPredictionStatus(message) {
      predictionStatus.textContent = message;
      if (predictionStatus.parentNode !== out) out.prepend(predictionStatus);
    }
    const waiting = () => showPredictionStatus(out.querySelector('.pp-image')
      ? 'Showing the previous prediction. Recalculating…' : 'Calculating prediction…');
    const failed = () => showPredictionStatus(out.querySelector('.pp-image')
      ? 'Showing the previous prediction; recalculation failed. Check the error and try again.'
      : 'Could not calculate the prediction. Check the error and try again.');
    const tone = toneSliders(save);
    const advisor = advice ? PhotoQuality.advisor(advice, (changes) => save(changes)) : null;
    /** Describe image tone only when it has changed. */
    const toneText = (view) => {
      if (!view.tone_used && !view.sharpness) return null;
      const t = {...TONE, ...(view.tone || {})};
      return h('p', {class: 'small'}, `Image adjusted: brightness ${value(t.brightness, 0)} %, contrast ${value(t.contrast, 0)} %, gamma ${value(t.gamma, 2)}. `
        + (view.sharpness ? `Sharpness ${value(view.sharpness, 0)}. ` : '')
        + 'The prediction and LightBurn file include these adjustments; LightBurn brightness, contrast, and gamma remain at their defaults (0 / 0 / 1) to avoid applying them twice.');
    };
    function show(view, sc) {
      const dots = dotted(view);
      tone.show(view);
      fill(kind, `Mode: ${kindName(view.kind || GRAYSCALE)}`);
      width.value = String(view.width_mm);
      width.removeAttribute('aria-invalid'); widthNote.textContent = '';
      byColour.checked = !!view.by_colour;
      byColour.disabled = dots;
      choice.value = view.colour_choice || 'drawing';
      choice.disabled = dots || !view.by_colour;
      contours.checked = !!view.contours;
      contours.disabled = dots || !view.by_colour;
      const info = view.picture;
      if (!info) {
        fill(out, h('div', {class: 'ge-placeholder stack'}, h('p', {class: 'alert warn'}, I18N.tr(view.problem)),
          h('p', {class: 'muted'}, 'Select a measured scale on the left. The image will remain, and Min and Max will use the measured range.')));
        fill(foot);
        fill(details, h('p', {class: 'muted'}, 'No prediction: this work’s scale has not been measured.'));
        return;
      }
      if (advisor) advisor.load(view);
      if (dots) { showDots(view, info, sc); return; }
      const t = info.time;
      const cleaning = t.layers.length > 1 ? t.layers[0] : null;      // the file cleans the titanium first (C00)
      const size = `${value(info.size_mm.width, 1)} × ${value(info.size_mm.height, 1)} mm`;
      const lined = info.contours_report && info.contours_report.share > 0 ? ' and contours' : '';
      const rampOnly = info.prediction_evidence && info.prediction_evidence.ramp_only;
      fill(out,
        info.applicability ? EvidenceSummary.applicability(info.applicability)
          : rampOnly ? h('p', {class: 'small alert warn ge-prediction-evidence'}, 'This mode has only been measured with a test scale. Prediction accuracy for photo engraving has not been verified.') : null,
        h('div', {class: 'pp-captions'}, h('span', {}, (info.by_colour ? 'Matched grayscale' : 'Image (as seen by LightBurn)') + lined), h('span', {}, 'Predicted appearance on titanium')),
        h('div', {class: 'pp-stage'}, h('img', {class: 'pp-image', src: info.preview, alt: 'Image and its prediction on titanium'})));
      if (stage) stage(out.querySelector('.pp-stage'), info.picture && info.picture.shown_width);
      const atSize = sizeText(info.scale_size);
      fill(foot,
        info.power_usage ? h('span', {class: 'ge-power-usage small'}, `Power for prepared grayscale: ${value(info.power_usage.range[0], 1)}–${value(info.power_usage.range[1], 1)} %; median ${value(info.power_usage.median, 1)} %. Min / Max settings: ${value(info.power_range[0], 1)} / ${value(info.power_range[1], 1)} %.`) : null,
        h('span', {}, h('strong', {}, `Engraving time: ≈ ${duration(t.seconds)}`), ` for ${size}`),
        atSize ? h('span', {title: atSize.long}, pill(atSize.short, atSize.tone)) : null,
        info.outside_share > 0 ? pill(`${value(info.outside_share * 100, 1)} % outside the scale`, 'warn') : null);
      fill(details,
        h('p', {}, h('strong', {}, `Engraving time: ≈ ${duration(t.seconds)}`), ` for ${size}${sc ? ` at scale ${value(sc.time_s_per_cm2, 0)} s/cm²` : ''}`
          + (cleaning ? `, cleaning ≈ ${duration(cleaning.seconds)}` : ''),
          h('span', {class: 'muted small'}, ` — estimate: ${cleaning ? 'cleaning the image rectangle first, then ' : ''}full-width image lines (in grayscale, white is also engraved at Min), speed, line spacing, and passes; acceleration and travel are excluded.`)),
        info.outside_share > 0 ? h('p', {class: 'alert warn'}, `${value(info.outside_share * 100, 1)} % of the image requires power outside the measured scale: those areas are hatched and have no prediction.`) : null,
        matchText(info.colour_match),
        contoursText(view, info),
        toneText(view),
        atSize ? h('p', {class: 'small'}, pill(atSize.short, atSize.tone), ' ', atSize.long, h('span', {class: 'muted'}, ' ' + SIZE_ABOUT)) : null,
        ramp ? rampOffer(view, info.scale_size, ramp) : null,
        variations ? variationsOffer(view, variations) : null,
        advisor ? advisor.el : null,
        h('p', {class: 'small'}, layer ? layer(info) : `LightBurn file: ${cleaning ? `C00 — cleaning ${cleaning.name} over the image rectangle first (scales were measured on cleaned plates); C01 — ` : ''}`
          + `image layer in grayscale mode: Min ${value(info.power_range[0], 1)} %, Max ${value(info.power_range[1], 1)} %, `
          + `${settingsText(view.scale, info.dpi)}. Image width ${value(info.size_mm.width, 1)} mm, with the top-left corner at the origin.`),
        h('ul', {class: 'small'}, info.notes.map((n) => h('li', {}, I18N.tr(n)))),
        info.by_colour && original ? h('details', {}, h('summary', {class: 'small'}, 'Original color image'),
          h('img', {class: 'pp-image', src: original, alt: 'Original image'})) : null,
        h('p', {class: 'muted small'}, 'A grayscale image is engraved as is. A color image is converted to grayscale either by LightBurn based on brightness or by matching grayscale to colors. '
          + CHOICE_ABOUT + ' Contours: ' + CONTOURS_ABOUT + ' The prediction and LightBurn file use the same image; the prediction is recalculated when the scale, Min, Max, '
          + 'width, matching, or contours change.'));
    }
    /** Работа в виде точками: картинка рядом с точками на титане издалека (оценка по шкале), точки вблизи, мощность и файл. */
    function showDots(view, info, sc) {
      const t = info.time, d = info.dots, name = kindName(view.kind), measured = d.measured, mapped = d.source === 'map';
      const photo = d.source === 'photo', from = photo ? recipeFrom(d.recipe) : null;
      const shot = photo && d.recipe.photo ? `фото № ${d.recipe.photo.pair_id} (${kindName(d.recipe.photo.kind)})` : null;     // the photograph of the dots
      const cleaning = t.layers.length > 1 ? t.layers[0] : null;
      const size = `${value(info.size_mm.width, 1)} × ${value(info.size_mm.height, 1)} мм`;
      const estimate = mapped ? 'оценка по карте цветов: этот вид на этих настройках ещё не гравировался'
        : photo ? `оценка${shot ? ' по ' + shot : ''}: этот вид на этих настройках ещё не гравировался` : 'оценка по шкале: этот вид ещё не гравировался';
      const source = mapped ? 'с карты цветов' : photo ? from : 'со шкалы';
      const settings = settingsText(firedSettings(view), info.dpi);
      fill(out,
        h('div', {class: 'pp-captions'}, h('span', {}, 'Картинка (как её видит LightBurn)'), h('span', {}, `${name} на титане — ${measured ? 'по измеренной пробе' : 'оценка'}`)),
        h('div', {class: 'pp-stage'}, h('img', {class: 'pp-image', src: info.preview, alt: `Картинка и она же в виде «${name}» на титане`})));
      if (stage) stage(out.querySelector('.pp-stage'), info.shown && info.shown.width);
      const atSize = mapped ? recipeSizeText(view.dot_recipe.size) : photo ? null : sizeText(info.scale_size);    // photo dots: measured on a picture
      fill(foot,
        h('span', {}, h('strong', {}, `Время гравировки: ≈ ${duration(t.seconds)}`), ` для ${size}`),
        h('span', {class: 'row'}, 'точки ', hexChip(d.hex), ` ${value(d.power, 1)} % ${source} на титане `, hexChip(d.clean_hex)),
        measured ? pill(`измерено: ${measured.tones} тонов этого вида`, 'ok') : pill(estimate, 'warn'),
        atSize ? h('span', {title: atSize.long}, pill(atSize.short, atSize.tone)) : null);
      fill(details,
        measured ? h('p', {}, h('strong', {}, `${name}. `), `Каждая точка бьёт на ${value(d.power, 1)} %${mapped ? ' на настройках цвета с карты цветов' : photo ? ` на настройках точек ${from}` : ''}. `
          + `Цвета картинки — как сфотографирована проба этого вида на этих настройках и этом титане: ${measured.tones} тонов. `
          + (mapped || photo ? 'To change dot color, select “Another color” above the image; ' : 'Мощность точек меняется на полосе шкалы; ')
          + 'на других настройках снова будет оценка, пока их не измерить.')
          : h('p', {}, h('strong', {}, `${name}. `), mapped
            ? [`Каждая точка бьёт на ${value(d.power, 1)} % на настройках цвета, выбранного на карте цветов: это цвет его заливки при ширине работы `, hexChip(d.hex)]
            : photo ? [`Каждая точка бьёт на ${value(d.power, 1)} % на настройках точек ${from}: это цвет точек на том фото `, hexChip(d.hex)]
              : [`Каждая точка бьёт на ${value(d.power, 1)} % — это цвет шкалы при этой мощности `, hexChip(d.hex)],
            '; между точками — очищенный титан ', hexChip(d.clean_hex), `. Тон — сколько точек: они покрывают ${value(d.struck_share * 100, 0)} % картинки, `
            + 'издалека глаз смешивает их с титаном. '
            + (mapped || photo ? 'To change dot color, select “Another color” above the image. To return dots to the scale, select “Back to scale” or click the scale strip.'
              : 'Change dot power by clicking a color on the scale strip. For another measured color, select “Color from map”.')),
        measured ? h('ul', {class: 'small'}, measured.notes.map((n) => h('li', {}, I18N.tr(n))))
          : h('p', {class: 'alert warn small'}, 'Это оценка: этот вид на этих настройках ещё не гравировался. '
            + (mapped ? 'Цвет точки взят с карты цветов — это цвет сплошной заливки этих настроек: в тёмных местах точки сливаются в такую же заливку, '
              + 'а отдельная точка — самая короткая строка, и на титане она может выйти светлее или другого оттенка. '
              : photo ? `Цвет точки — ${shot ? `как на ${shot}, где сфотографированы точки этих настроек` : 'по ближайшей сфотографированной гравировке'}. `
              : 'Цвет точки взят со шкалы, измеренной строками; точка — самая короткая строка, а цвет на титане зависит от длины строки, поэтому настоящие точки могут выйти другого оттенка. ')
            + 'Узор точек — по опубликованному алгоритму; LightBurn ставит точки своим кодом, узор может отличаться, доля точек — та же.'),
        mapped && view.dot_recipe.missing ? h('p', {class: 'alert warn small'}, 'Этого цвета больше нет среди измерений карты цветов: оценка — по цвету, каким он был при выборе. '
          + 'Select a color again (“Another color”) or return dots to the scale.') : null,
        ramp ? rampOffer(view, info.scale_size, ramp) : null,
        variations ? variationsOffer(view, variations) : null,
        advisor ? advisor.el : null,
        h('figure', {class: 'ge-closeup'}, h('img', {src: info.closeup, alt: `Точки вида «${name}» вблизи`}),
          h('figcaption', {class: 'small muted'}, `Точки вблизи: квадрат ${value(info.closeup_mm, 0)} × ${value(info.closeup_mm, 0)} мм из середины картинки, точка в точку при ${info.dpi} dpi `
            + `(каждая точка — ${info.closeup_px} пикселя экрана), цвет точки — ${source}.`)),
        h('p', {}, h('strong', {}, `Время гравировки: ≈ ${duration(t.seconds)}`), ` для ${size}${sc ? ` на шкале ${value(sc.time_s_per_cm2, 0)} s/cm²` : ''}`
          + (cleaning ? `, из них чистка ≈ ${duration(cleaning.seconds)}` : ''),
          h('span', {class: 'muted small'}, ' — оценка сверху: строки на всю ширину картинки, как в градациях серого; белые места лазер в виде точками пролетает быстрее.')),
        toneText(view),
        atSize ? h('p', {class: 'small'}, pill(atSize.short, atSize.tone), ' ', atSize.long, h('span', {class: 'muted'}, ' ' + SIZE_ABOUT)) : null,
        h('p', {class: 'small'}, layer ? layer(info) : `Файл LightBurn: ${cleaning ? `C00 — чистка ${cleaning.name} по прямоугольнику картинки, первой; C01 — ` : ''}`
          + `слой-изображение в режиме «${name}»: мощность ${value(d.power, 1)} % (Min = Max — каждая точка бьёт на ней), ${settings}${mapped ? ' — настройки цвета с карты цветов' : photo ? ` — настройки точек ${from}` : ''}. `
          + `Картинка — как загружена, ${value(info.size_mm.width, 1)} мм в ширину, левый верхний угол в нуле: точки ставит LightBurn.`),
        h('p', {class: 'muted small'}, 'Подбор серых под цвета, контуры и правила частей — для градаций серого: в виде точками все точки одного цвета, и картинка '
          + 'гравируется как загружена. Вернуться к градациям серого — «Вид» над картинкой; всё, что было для них задано, сохранилось.'));
    }
    const inputs = h('div', {class: 'ge-inputs'}, kind,
      h('label', {class: 'row'}, h('span', {class: 'small'}, 'Ширина, мм'), width, Forms.describe(width, 'pictureWidth')), widthNote,
      h('label', {class: 'row', title: 'Серые подбираются под цвета картинки на этой шкале'}, byColour, h('span', {class: 'small'}, 'Подобрать серые под цвета')),
      choice,
      h('label', {class: 'row', title: 'Контуры: ' + CONTOURS_ABOUT}, contours, h('span', {class: 'small'}, 'Контуры')));
    return {inputs, tone: tone.el, out, foot, details, comparison, compare, show, waiting, failed};
  }

  const OBJECT_NAMES = {background: 'Фон', hair: 'Волосы', face_skin: 'Кожа лица', body_skin: 'Кожа тела', clothes: 'Одежда', other: 'Другое (очки…)',
    lips: 'Губы', eyes: 'Глаза'};
  /** Имя объекта по его ключу: вид, у кусков фона — ещё номер («Фон 2»). */
  const objectName = (key) => { const [kind, piece] = String(key).split('-'); return (OBJECT_NAMES[kind] || kind) + (piece ? ` ${+piece + 1}` : ''); };
  const THEMES = [['warm', 'Тёплая', 'Кожа — самым светлым тёплым цветом шкалы, губы — самым красным, остальное — тёплыми цветами по своей светлоте'],
    ['cool', 'Холодная', 'Кожа и губы тёплые, остальное — холодными цветами шкалы по своей светлоте'],
    ['contrast', 'Контрастная', 'Крупные объекты первыми, каждый — цветом шкалы, самым далёким от уже данных'],
    ['random', 'Случайно', 'Каждому объекту — случайный цвет шкалы; ещё раз — другие цвета']];
  const COLOURING_ABOUT = 'Как в раскраске: каждому объекту — свой основной цвет шкалы. Его светлые и тёмные места ложатся вокруг этого цвета, '
    + 'по соседним цветам шкалы (шаг не больше 5 ΔE, в одном семействе — от золотого не прыгает в синий), поэтому губы остаются губами, очки — очками. '
    + '«Светлее/темнее» сдвигает тона объекта по его семейству. Объект без цвета — «Авто»: как вся картинка при «Сохранить рисунок».';

  /** Вкладка «Раскраска» (0.21.0): объекты картинки — фон и его куски, волосы, кожа, одежда, губы, глаза, другое (очки) — каждому свой
      основной цвет: выберите объект, щёлкните цвет шкалы; «Светлее/темнее»; «Авто» убирает цвет. Темы и «Случайно» дают цвета всем сразу,
      AI — по просьбе своими словами (с картинкой, если разрешено во вкладке «AI»). Любой шаг отменяет «Отменить» в шапке. ``save`` сохраняет
      настройки работы, ``send(path, body)`` — тему или просьбу к AI; оба отдают ошибку или null. ``base`` — адрес API работы или фотозоны. */
  function colourTab(base, save, send) {
    const status = h('p', {class: 'small', role: 'status', hidden: true});
    const themes = h('div', {class: 'row'});
    // ai_colouring.MAX_TEXT: the description is 1 to 400 characters once trimmed; a longer text is refused with its length instead of being cut at 400 as it is typed
    const wishForm = Forms.create();
    const wish = h('input', {type: 'text', placeholder: 'например: очки золотом, фон синий, губы красные'});
    const wishField = wishForm.add('wish', 'Как раскрасить — своими словами', wish, {required: true, maxLength: 400});
    const aiNote = h('div');
    const palette = h('div', {class: 'ge-palette', role: 'group', 'aria-label': 'Scale colors'});
    const list = h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Ищем объекты картинки…'));
    const notes = h('ul', {class: 'small'});
    const overlay = h('div');
    const blocked = h('p', {class: 'alert warn small', hidden: true});
    let view = null, found = null, foundKey = null, selected = null, asking = false;
    const colours = () => (view && view.colouring) || {};
    const options = () => (found && found.options) || [];
    const hexOf = (c) => { const o = options().find((x) => Math.abs(x.power - c.power) < 0.01); return o ? o.hex : null; };
    /** Цвета объектов ``next`` (ключ → цвет): работа переходит на раскраску по объектам. */
    const colourWith = (next) => save({by_colour: true, colour_choice: 'objects', colouring: next});
    function setColour(key, power) {
      const was = colours()[key];
      colourWith({...colours(), [key]: {power, shift: was ? was.shift : 0}});
    }
    function setShift(key, shift) { colourWith({...colours(), [key]: {...colours()[key], shift}}); }
    function clear(key) { const next = {...colours()}; delete next[key]; colourWith(next); }
    async function ask() {
      if (asking) return;
      const v = wishForm.collect();
      if (!v) { status.hidden = true; return; }                          // the reason stands beside the box
      asking = true;
      enable();
      status.textContent = 'AI думает… обычно это до минуты.';
      status.hidden = false;
      const failed = await send(`${base}/ai-theme`, {wish: wish.value});
      asking = false;
      status.textContent = failed ? failed.message : '';
      status.hidden = !failed;
      enable();
    }
    const askButton = btn('Раскрасить по просьбе', ask, 'primary btn-small');
    askButton.setAttribute('title', 'AI видит объекты, их цвета на фото и цвета шкалы и даёт каждому объекту основной цвет шкалы');
    wish.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); ask(); } });
    const auto = btn('Всё — авто', () => colourWith({}), 'btn-small');
    auto.setAttribute('title', 'Убрать цвета всех объектов: вся картинка как при «Сохранить рисунок»');
    fill(themes, THEMES.map(([name, label, about]) => {
      const b = btn(label, () => send(`${base}/theme`, name === 'random' ? {name, seed: Math.floor(Math.random() * 1e9)} : {name}), 'btn-small');
      b.setAttribute('title', about);
      return b;
    }), auto);
    function enable() {
      const off = !view || dotted(view) || !view.picture;
      for (const b of themes.querySelectorAll('button')) b.disabled = off;
      auto.disabled = off || !Object.keys(colours()).length;
      askButton.disabled = off || asking || !!view.ai_missing;
      wish.disabled = off;
    }
    function rows() {
      if (!found || !view) return;
      const off = dotted(view) || !view.picture;
      const picked = options().length && selected ? (colours()[selected] || null) : null;
      fill(palette, options().map((o) => {
        const b = h('button', {type: 'button', class: 'ge-swatch' + (picked && Math.abs(picked.power - o.power) < 0.01 ? ' is-chosen' : ''), style: `background:${o.hex}`,
          title: `${value(o.power)} % · L* ${value(o.lab[0], 0)}`, 'aria-label': `Цвет шкалы ${value(o.power)} %`, disabled: off || !selected,
          onClick: () => setColour(selected, o.power)});
        return b;
      }));
      fill(list, found.objects.length ? h('ul', {class: 'ge-objects'}, found.objects.map((o) => {
        const c = colours()[o.key] || null;
        const shift = h('input', {type: 'range', min: '-1', max: '1', step: '0.25', value: String(c ? c.shift : 0), disabled: off || !c,
          'aria-label': `Светлее или темнее: ${objectName(o.key)}`, title: 'Темнее ← → светлее'});
        const shiftNote = Forms.describe(shift, 'objectShift', {extra: 'меньше нуля — темнее, больше — светлее; шаг 0,25'});
        shift.addEventListener('change', () => setShift(o.key, +shift.value));
        const clearIt = btn('Авто', () => clear(o.key), 'btn-small');
        clearIt.disabled = off || !c;
        clearIt.setAttribute('title', 'Убрать цвет объекта: как при «Сохранить рисунок»');
        return h('li', {class: 'ge-object' + (o.key === selected ? ' is-selected' : ''), 'aria-current': o.key === selected ? 'true' : null,
          onClick: (ev) => { if (ev.target.closest('button,input')) return; selected = o.key; rows(); }},
          h('span', {class: 'ge-nowrap'}, h('span', {class: 'sw', style: `background:${o.tint}`, title: 'цвет объекта на картинке объектов'}), objectName(o.key)),
          h('span', {class: 'small muted ge-nowrap'}, `${value(o.share * 100, 1)} % · на фото `, hexChip(o.hex)),
          h('span', {class: 'row ge-nowrap'}, c ? hexChip(hexOf(c)) : pill('авто', 'muted'), c ? `${value(c.power)} %` : null),
          h('span', {class: 'row ge-nowrap'}, h('span', {class: 'small muted'}, 'темнее'), shift, shiftNote, h('span', {class: 'small muted'}, 'светлее'), clearIt));
      })) : h('p', {class: 'muted'}, 'На картинке не нашлось объектов: раскрашивать нечего.'));
      fill(notes, (found.notes || []).map((n) => h('li', {}, I18N.tr(n))));
    }
    async function load() {
      const key = view ? JSON.stringify([view.scale, view.min_power, view.max_power, view.width_mm]) : null;
      if (key === foundKey) { rows(); return; }
      foundKey = key;
      try {
        const next = await get(`${base}/objects`);
        if (key !== foundKey) return;
        found = next;
        if (!selected || !found.objects.some((o) => o.key === selected)) selected = found.objects.length ? found.objects[0].key : null;
        fill(overlay, h('details', {}, h('summary', {class: 'small'}, 'Объекты на картинке'),
          h('img', {class: 'pp-image', src: found.picture, alt: 'Объекты картинки, каждый своим цветом'})));
        rows();
      } catch (e) { if (key === foundKey) fill(list, h('p', {class: 'alert bad'}, e.message)); }
    }
    function show(next) {
      view = next;
      blocked.textContent = dotted(view) ? 'Раскраска по объектам — для градаций серого: в виде точками каждая точка бьёт на одной мощности. Вид меняется кнопкой «Вид» над картинкой; цвета объектов сохранены.'
        : !view.picture ? 'Шкала этой работы не измерена: цветов, чтобы раскрашивать, нет.' : '';
      blocked.hidden = !blocked.textContent;
      if (!wish.value && view.ai_theme) wish.value = view.ai_theme.wish;
      fill(aiNote, view.ai_theme ? h('p', {class: 'small'}, h('strong', {}, 'AI: '), view.ai_theme.note || 'без пояснения',
        h('span', {class: 'muted'}, ` — на «${view.ai_theme.wish}»${view.ai_theme.photo ? ', с картинкой' : ''}`)) : null);
      enable();
      load();
    }
    const el = h('div', {class: 'stack'},
      h('p', {class: 'small'}, COLOURING_ABOUT),
      blocked,
      h('h4', {}, 'Темы'), themes,
      h('div', {class: 'row ge-ask'}, wishField, askButton), status, aiNote,
      h('h4', {}, 'Объекты'),
      h('p', {class: 'small muted'}, 'Выберите объект в списке и щёлкните его цвет на полосе цветов шкалы.'),
      palette, list, notes, overlay,
      h('p', {class: 'small muted'}, 'Scale colors — при Min и Max работы, не ближе 8 ΔE друг к другу. Картинку AI получает, только если это разрешено во вкладке «AI». '
        + 'Объекты находит модель людей (кожа, волосы, одежда, другое), губы и глаза — поиск лица, куски фона — по их цвету.'));
    return {el, show};
  }

  const PART_NAMES = {background: 'Фон', hair: 'Волосы', body_skin: 'Кожа тела', face_skin: 'Кожа лица', clothes: 'Одежда', other: 'Другое'};
  const RULES = [['as_is', 'Как есть'], ['photo', 'Цвета фото'], ['neutral', 'Чёрно-белое'], ['colour', 'Цвет'], ['even', 'Один тон']];
  const WITH_TARGET = ['colour', 'even'];
  const AI_MISSING = {library: 'AI недоступен: в окружении приложения нет библиотеки openai (как её поставить — в README). Правила частей можно задать вручную.',
    key: 'AI выключен: не задан ключ OpenAI (его вводят на экране «Сеть»). Правила частей можно задать вручную.'};

  /** Вкладка «AI» работы (REQ-062): пожелание своими словами, разрешение отправить уменьшенную картинку, «Попросить AI» (от нынешних
      правил: AI меняет то, о чём просят) и «Заново с картинки» (AI начинает с картинки без правил), его ответ; части картинки, найденные
      моделью, с правилом каждой (его можно поменять вручную), цветом-целью и тем, насколько близко к нему подходят серые шкалы, «Все части
      как есть»; части поверх картинки. Серые всегда подбираются на шкале работы, не моделью; любой шаг отменяет «Отменить» в шапке.
      ``save`` сохраняет правила и разрешение, ``ask(wish, fresh)`` спрашивает AI; оба отдают ошибку или null. ``base`` — адрес API работы
      или фотозоны. */
  function aiTab(base, save, ask) {
    const wishForm = Forms.create();
    const wish = h('textarea', {rows: 3, placeholder: 'например: всё как есть, чёрно-белое; платье фиолетовым, ярким; кожу равномерно светлой'});
    const wishField = wishForm.add('wish', 'Что изменить в картинке', wish, {required: true, maxLength: 400});     // ai_colouring.MAX_TEXT
    const photo = h('input', {type: 'checkbox'});
    const status = h('p', {class: 'small', role: 'status', hidden: true});
    const missing = h('p', {class: 'alert warn small', hidden: true});
    const answer = h('div', {class: 'stack'});
    const table_ = h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Ищем части картинки…'));
    const overlay = h('div');
    let view = null, parts = null, asking = false;
    photo.addEventListener('change', () => save({ai_photo: photo.checked}));
    async function request(fresh) {
      if (asking) return;
      if (!wishForm.collect()) { status.hidden = true; return; }
      asking = true;
      enable();
      status.textContent = 'AI думает… обычно это до минуты.';
      status.hidden = false;
      const failed = await ask(wish.value, fresh);
      asking = false;
      status.textContent = failed ? failed.message : '';
      status.hidden = !failed;
      enable();
    }
    const button = btn('Попросить AI', () => request(false), 'primary btn-small');
    const again = btn('Заново с картинки', () => request(true), 'btn-small');
    button.setAttribute('title', 'AI видит нынешние правила частей и меняет то, о чём вы просите');
    again.setAttribute('title', 'AI начинает с картинки без правил частей: его ответ заменяет их все');
    const plain = btn('Все части как есть', () => save({rules: []}), 'btn-small');
    plain.setAttribute('title', 'Убрать правила всех частей: картинка гравируется как есть');
    function enable() {
      button.disabled = again.disabled = asking || !!(view && view.ai_missing);
      plain.disabled = !(view && view.rules.length);
    }
    function setRule(part, kind, hex) {
      const others = view.rules.filter((r) => r.part !== part);
      save({rules: kind === 'as_is' ? others : [...others, WITH_TARGET.includes(kind) ? {part, kind, hex} : {part, kind}]});
    }
    function rows() {
      if (!parts) return;
      const report = (view.picture && view.picture.rules_report) || [];
      fill(table_, parts.length ? table(['Часть', 'Доля', 'Цвет', 'Правило', 'ΔE к цели'], parts.map((p) => {
        const name = PART_NAMES[p.part] || p.part;
        const rule = view.rules.find((r) => r.part === p.part) || {kind: 'as_is'};
        const select = h('select', {'aria-label': `Правило: ${name}`}, RULES.map(([kind, label]) => h('option', {value: kind}, label)));
        select.value = rule.kind;
        select.addEventListener('change', () => setRule(p.part, select.value, rule.hex || p.hex));
        const target = WITH_TARGET.includes(rule.kind) ? h('input', {type: 'color', value: rule.hex || p.hex, 'aria-label': `Цвет-цель: ${name}`}) : null;
        if (target) target.addEventListener('change', () => setRule(p.part, rule.kind, target.value));
        const near = report.find((r) => r.part === p.part);
        return [h('span', {class: 'ge-nowrap'}, h('span', {class: 'sw', style: `background:${p.tint}`, title: 'цвет части на картинке частей'}), ` ${name}`),
          h('span', {class: 'ge-nowrap'}, `${value(p.share * 100, 1)} %`), hexChip(p.hex), h('span', {class: 'row ge-rule'}, select, target),
          near && near.median_de != null ? `≈ ${value(near.median_de, 1)}` : h('span', {class: 'muted'}, '—')];
      }), '', true) : h('p', {class: 'muted'}, 'Модель не нашла на картинке частей: правила задать не для чего.'));
    }
    function show(next) {
      view = next;
      photo.checked = !!view.ai_photo;
      missing.textContent = AI_MISSING[view.ai_missing] || '';
      missing.hidden = !view.ai_missing;
      enable();
      if (!wish.value && view.ai) wish.value = view.ai.wish;
      fill(answer, view.ai ? h('p', {class: 'small'}, h('strong', {}, 'AI: '), view.ai.note || 'без пояснения',
        h('span', {class: 'muted'}, ` — на «${view.ai.wish}»${view.ai.fresh ? ', заново с картинки' : ''}${view.ai.photo ? ', с картинкой' : ''}`)) : null);
      rows();
    }
    get(`${base}/parts`).then((found) => {
      parts = found.parts;
      fill(overlay, h('details', {}, h('summary', {class: 'small'}, 'Части на картинке'),
        h('img', {class: 'pp-image', src: found.picture, alt: 'Части картинки, каждая своим цветом'})));
      if (view) rows();
    }, (e) => fill(table_, h('p', {class: 'alert bad'}, e.message)));
    const el = h('div', {class: 'stack'},
      h('p', {class: 'small'}, 'Скажите своими словами, что изменить в картинке. AI предложит правило для каждой части — фона, волос, кожи, одежды; '
        + 'серые подбираются на шкале работы по вашим измерениям, поэтому видно, что на этом титане достижимо.'),
      wishField, h('label', {class: 'small ge-check'}, photo, h('span', {}, 'Отправить AI уменьшенную картинку (без этого — только числа: части и их цвета)')),
      h('div', {class: 'row'}, button, again), missing, status, answer,
      h('div', {class: 'row ge-parts-head'}, h('h4', {}, 'Части картинки'), plain), table_, overlay,
      h('p', {class: 'small muted'}, 'Как есть — серые картинки; цвета фото — для каждого пикселя серый с ближайшим цветом на шкале; чёрно-белое — только серые, '
        + 'которые на титане выходят почти серыми; цвет — цель, светлое и тёмное части сохраняются; один тон — один серый на всю часть: он стирает всё внутри неё (глаза, брови и губы — часть кожи лица, '
        + 'поэтому ровную светлую кожу лучше задать цветом). '
        + '«ΔE к цели» — медиана ΔE между желаемым цветом и тем, что даёт шкала. Ответ AI и любое изменение отменяются кнопкой «Отменить» вверху (Ctrl+Z).'));
    return {el, show};
  }

  const KIND_ABOUT = {
    power: (k) => `Многоцветная: серый задаёт мощность от Min ${value(k.min_power, 1)} % до Max ${value(k.max_power, 1)} %, мощность на титане — цвет. По измеренной шкале.`,
    dots: (k) => `Точки одного цвета на очищенном титане, тон — сколько точек. Точки ${value(k.power, 1)} %.`,
    edges: (k) => `Точки по краям рисунка, ровные места остаются титаном. Точки ${value(k.power, 1)} %.`};

  const KINDS_ABOUT = 'Градации серого измерены вашими шкалами; виды точками показаны оценкой: точка — цвет шкалы при мощности точек, между точками — '
    + 'очищенный титан. Вид можно поменять в работе в любой момент.';

  /** The tiles of «Какая гравировка?»: every kind that colours titanium, each with the work's picture as it would come out in it (a dot kind
      is an estimate from the scale). The tile of ``current`` is marked with ``tag``; a click on a tile calls ``pick`` with its kind, and
      ``mark(key)`` moves the mark. Shared by the second step of «Новая работа», the «Вид» button of a work and of a photo zone; ``base`` is the
      API address of the work or the zone. */
  function kindTiles(base, current, pick, tag) {
    const grid = h('div', {class: 'ge-kinds'}, h('p', {class: 'muted'}, 'Считаем, как картинка выйдет в каждом виде…'));
    let tiles = [];
    const mark = (key) => {
      current = key;
      for (const t of tiles) {
        const on = t.key === key;
        t.el.classList.toggle('is-chosen', on);
        t.el.setAttribute('aria-pressed', String(on));
        fill(t.tag, on ? pill(tag, 'ok') : null);
      }
    };
    get(`${base}/kinds`).then((d) => {
      if (d.problem) { fill(grid, h('p', {class: 'alert warn'}, I18N.tr(d.problem))); return; }
      tiles = d.kinds.map((k) => {
        const name = kindName(k.key);
        const about = (KIND_ABOUT[k.family] || KIND_ABOUT.dots)(k);
        const slot = h('span', {});
        const el = h('button', {type: 'button', class: 'ge-kind', onClick: () => pick(k.key)},
          h('img', {src: k.picture, alt: `Картинка в виде «${name}»`, loading: 'lazy'}),
          h('span', {class: 'ge-kind-head'}, h('strong', {}, name), slot),
          h('span', {class: 'small'}, k.hex ? hexChip(k.hex) : null, k.hex ? ' ' : null, about),
          k.estimate ? h('span', {class: 'small muted'}, k.basis === 'inferred' ? 'оценка; узор LightBurn не опубликован — показан похожий' : 'оценка: этот вид ещё не гравировался') : null);
        return {key: k.key, el, tag: slot};
      });
      fill(grid, tiles.map((t) => t.el));
      mark(current);
    }, (e) => fill(grid, h('p', {class: 'alert bad'}, e.message)));
    return {el: grid, mark};
  }

  /** «Вид» of a work: «Какая гравировка?» with the work's picture in each kind and its kind marked; a click on another kind switches the
      work to it («Отменить» takes it back). */
  function kindChooser(base, current, choose) {
    const tiles = kindTiles(base, current, (key) => { dialog.close(); if (key !== current) choose(key); }, 'сейчас');
    const dialog = modal('Какая гравировка?', h('div', {class: 'stack'},
      h('p', {class: 'small'}, 'Под каждым видом — картинка работы, какой она выйдет на титане на её шкале. ' + KINDS_ABOUT), tiles.el),
      [{label: 'Закрыть', run: (m) => m.close()}]);
    return dialog;
  }

  return {value, when, materialLabel, titaniumLabel, sameScale, settingsText, modeQuery, GRAYSCALE, dotted, fromMap, firedSettings, kindName, hexChip, mm, mmList,
    sizeText, SIZE_ABOUT, scaleBar, scaleCard, newSlots, emptySlots, scaleDetail, calibrationControls, workPicture, resultCards, exportedResults, colourTab, aiTab, kindTiles, kindChooser, KINDS_ABOUT};
})();
