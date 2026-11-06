/* Compare accepted photo engravings with predictions reconstructed from earlier measurements (DEC-117, REQ-003). */
'use strict';
const PredictionReview = (() => {
  const {h, fill, pill, get, swatch} = App;
  const value = (v, d = 1) => (v == null ? '—' : String(+(+v).toFixed(d)));
  const mm = (v) => `${value(v)} mm`;
  const plate = (p) => `${p.name || `plate #${p.id}`}${p.thickness_mm != null ? ` (${mm(p.thickness_mm)})` : ''}`;
  const cleaned = (c) => (c == null ? 'cleaning unspecified' : c ? 'cleaned' : 'not cleaned');
  const HOW = {witness: 'cleaning witness', lightest: 'lightest tone'};
  const reading = (r) => `${r.photo}: L* ${value(r.L)} (${HOW[r.how] || r.how})`;
  const lighter = (d) => `${d > 0 ? 'lighter' : 'darker'} by ${value(Math.abs(d))} L*`;
  const REASON = {
    no_points: 'this layer’s tones were excluded from the scale (the gray-to-color relationship is weak or an image overlays the fills); there is nothing to compare.',
    first: 'nothing with these settings had been measured before this engraving, so no prediction was available; it now contributes to the scale.',
    kind: 'earlier colors were measured differently from this photo (with or without a chart), so they cannot be compared.',
    outside: 'its power values lie outside the earlier measurements, so no prediction was available.'};

  function sizeText(c) {
    if (c.how === 'measured') return [`Line width ${mm(c.row_mm)} was measured before this engraving.`, 'ok'];
    if (c.how === 'between') return [`Line width ${mm(c.row_mm)} falls between measured widths ${c.from_mm.map((v) => value(v)).join(' and ')} mm; the prediction is interpolated.`, ''];
    if (c.how === 'outside') {
      return [`Line width ${mm(c.row_mm)} is outside previously measured widths (${c.measured_mm.map((v) => value(v)).join('; ')} mm). The prediction uses the nearest width, `
        + `${mm(c.from_mm[0])}, without adjustment. Lines cool differently at another width, so the same power can produce different colors.`, 'warn'];
    }
    return ['Line width is unknown; the prediction uses all measurements with these settings.', ''];
  }
  function plateText(c) {
    if (!c.differs) return [`Same plate: ${plate(c.own)}.`, 'ok'];
    return [`The prediction uses engravings on ${c.used.map(plate).join(', ')}; this engraving is on ${plate(c.own)}.`, 'warn'];
  }
  function cleaningText(c) {
    const used = [...new Set(c.used.map((u) => cleaned(u.cleans)))].join(', ');
    if (c.own == null) return [`Cleaning for this engraving is unspecified; prediction engravings: ${used}.`, ''];
    if (!c.differs) return [`Same cleaning as the prediction engravings: ${cleaned(c.own)}.`, 'ok'];
    return [`This engraving is ${cleaned(c.own)}; prediction engravings are ${used}.`, 'warn'];
  }
  function photoText(c) {
    if (!c.own) return ['No bare titanium is visible in this photo, so lighting cannot be compared.', ''];
    const parts = [`Bare titanium in this photo: ${reading(c.own)}.`];
    if (c.used.length) {
      const surface = c.used.every((r) => r.same_surface) && Math.abs(c.dL_used) >= 3 ? ' The plate and cleaning are the same, so the difference is photo lighting rather than metal.' : '';
      parts.push(`Prediction photos: ${c.used.map(reading).join('; ')}; this photo is ${lighter(c.dL_used)}.${surface}`);
    }
    if (c.same_surface.length) {
      parts.push(`On the same plate with the same cleaning: ${c.same_surface.map(reading).join('; ')}`
        + (Math.abs(c.dL_same) >= 3 ? `; this photo is ${lighter(c.dL_same)}, due to lighting rather than metal.` : '; the photo lighting is the same.'));
    }
    return [parts.join(' '), c.differs ? 'warn' : 'ok'];
  }
  const CAUSE = {size: sizeText, plate: plateText, cleaning: cleaningText, photo: photoText};

  function shift(layer) {
    const dl = layer.median_dL, db = layer.median_db;
    const light = Math.abs(dl) < 1 ? 'the predicted lightness' : `${dl > 0 ? 'lighter' : 'darker'} than predicted by ${value(Math.abs(dl))} L*`;
    const hue = Math.abs(db) < 3 ? '' : `, ${db > 0 ? 'yellower' : 'bluer'} by ${value(Math.abs(db))} b*`;
    return `Result: ${light}${hue} (medians across tones).`;
  }
  function tones(layer) {
    return h('details', {}, h('summary', {}, `Tones: prediction and result (${layer.bands.length})`),
      h('ul', {class: 'pr-tones'}, layer.bands.map((b) => h('li', {class: 'pr-tone'},
        h('span', {class: 'pr-power'}, `${value(b.power)} %`),
        h('span', {}, swatch(b.predicted), ` L* ${value(b.predicted[0], 0)}`), h('span', {class: 'muted'}, '→'),
        h('span', {}, swatch(b.lab), ` L* ${value(b.lab[0], 0)}`),
        pill(`${value(b.de)} ΔE`, b.de > layer.tolerance_de ? 'warn' : 'ok')))));
  }
  /** Group layers that cannot be compared by reason. */
  function reasons(layers, all) {
    const by = new Map();
    for (const layer of layers) by.set(layer.reason, [...(by.get(layer.reason) || []), layer.name]);
    return [...by].map(([reason, names]) => h('p', {class: 'small muted'},
      `${names.length === all ? 'Prediction' : `${names.length === 1 ? 'Layer' : 'Layers'} ${names.join(', ')}`}: ${REASON[reason] || reason}`));
  }
  function layerBlock(layer, several) {
    const name = several ? `Layer ${layer.name}: ` : '';
    const causes = layer.causes.map((c) => { const [text, kind] = CAUSE[c.code](c); return h('li', {class: kind ? `pr-${kind}` : ''}, text); });
    return h('div', {class: 'stack pr-layer'},
      h('div', {class: 'row'}, h('strong', {}, `${name}Prediction based on ${layer.engravings} previously accepted ${layer.engravings === 1 ? 'engraving' : 'engravings'}`),
        pill(`median ${value(layer.median_de)} ΔE`, layer.median_de > layer.tolerance_de ? 'warn' : 'ok')),
      h('p', {class: 'small'}, `Tones compared: ${layer.compared} · maximum ${value(layer.max_de)} ΔE · within ${value(layer.tolerance_de, 0)} ΔE: `
        + `${value(layer.within * 100, 0)} %. ${shift(layer)}`),
      largest(layer), h('h4', {}, 'Prediction basis'), h('ul', {class: 'pr-causes small'}, causes), tones(layer));
  }
  const TOP_TONES = 3;                       // the tones that came out furthest from the prediction, named before the full list
  /** Largest differences, ordered by ΔE. */
  function largest(layer) {
    const top = [...layer.bands].sort((a, b) => b.de - a.de).slice(0, TOP_TONES);
    return top.length ? h('p', {class: 'small'}, h('strong', {}, 'Largest differences: '), top.map((b) => `${value(b.power)} % — ${value(b.de)} ΔE`).join('; '), '.') : null;
  }
  function overallText(o) {
    if (!o || !o.all.tones) return null;
    return h('p', {class: 'small muted'}, `Across accepted photo engravings, prior predictions differed by ${value(o.all.median_de)} ΔE (median across ${o.all.tones} tones, `
      + `${o.all.engravings} engravings); where width was measured beforehand: ${o.size_measured.tones ? `${value(o.size_measured.median_de)} ΔE` : 'none yet'}.`);
  }

  /** Review card for an accepted photo and the overall comparison. */
  function card(review, overall) {
    if (!review.layers.length) return null;
    const several = review.layers.length > 1;
    return h('div', {class: 'stack pr-card'}, h('h3', {}, 'Prediction and result'),
      h('p', {class: 'small muted'}, 'Compare the photo with the scale prediction for this line width, based on previously accepted engravings.'),
      h('p', {class: 'small', role: 'note'}, h('strong', {}, 'Basis: reconstruction. '), 'This prediction was not saved with the file; it was reconstructed from engravings '
        + 'accepted earlier. It describes what previous measurements could have predicted, not a promise stored in the file.'),
      ...review.layers.filter((layer) => !layer.reason).map((layer) => layerBlock(layer, several)),
      ...reasons(review.layers.filter((layer) => layer.reason), review.layers.length), overallText(overall));
  }

  /** Load the review while the target remains visible. */
  async function load(pairId, box, still) {
    try {
      const [review, overall] = await Promise.all([get(`/pairs/${pairId}/prediction-review`), get('/prediction-reviews')]);
      if (still()) fill(box, card(review, overall));
    } catch (e) {
      if (still()) fill(box, h('p', {class: 'small muted'}, `Prediction and result could not be compared: ${e.message}`));
    }
  }

  return {card, load};
})();
