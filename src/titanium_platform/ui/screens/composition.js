/* Work composition (REQ-053, DEC-095): fills, photo engraving, visible area and covered samples, derived from the file before photo review. */
'use strict';
const Composition = (() => {
  const {h, num, facts} = App;
  const KIND = {cleaning: 'plate cleaning', fill: 'fill', photo: 'photo engraving', depth: 'depth (3D slice)'};
  const pct = (v) => (v == null ? '—' : `${num(v, 1)}%`);

  function verdict(c) {
    const s = c.share, photo = c.layers.some((l) => l.kind === 'photo' || l.kind === 'depth'), fills = c.layers.some((l) => l.kind === 'fill');
    if (c.mixed && c.picture_over_fills) return `Photo engraving overlays fills on ${pct(s.both)} of the work area: the visible color mixes fill and dots.`;
    if (c.mixed) return `Mixed work: fills (${pct(s.fill_only)}) and photo engraving (${pct(s.photo_only)}) lie side by side. The image is cut out where fills appear; only ${pct(s.both)} is under both layers.`;
    if (photo) return 'Photo engraving only' + (c.cleaning_layer != null ? ' on a cleaned plate.' : '.');
    return fills ? 'Vector fills only.' : 'No layers engrave an area.';
  }

  const segment = (cls, v, text) => (v ? h('span', {class: 'comp-' + cls, style: `width:${v}%`, title: `${text} ${pct(v)}`}) : null);

  const kindText = (l) => KIND[l.kind] + (l.mode ? ` · ${PhotoModes.label(l.mode)}` : '') + (l.hidden ? ' · hidden' : '');
  const seen = (l) => (l.engraves ? `visible ${pct(l.visible_percent)}` : 'output disabled');
  const picture = (l) => [`image opaque over ${pct(l.opaque_percent)}`, `engraves ${pct(l.struck_percent)}`,
    l.dot_density_percent != null ? `dots cover ${pct(l.dot_density_percent)} of the area on average` : null].filter(Boolean).join(' · ');

  /** The layers of the file as a short list (DEC-090; a matrix plate has a hundred): a line each — name, what it is, area, how much of it
      stays visible; what a picture layer covers under its line. ``key`` keeps the list's choices per photograph. */
  function layerList(layers, key) {
    const pictureLayer = (l) => l.kind === 'photo' || l.kind === 'depth';
    return App.list({id: key == null ? null : `comp:${key}`, items: layers, key: (l) => String(l.index),
      row: (l) => [h('strong', {}, I18N.name(l.name)), h('span', {class: 'lst-text muted small'}, kindText(l)),
        h('span', {class: 'small'}, `${num(l.area_mm2, 0)} mm²`), h('span', {class: 'small' + (l.engraves ? '' : ' muted')}, seen(l))],
      details: (l) => facts([['Layer', I18N.name(l.name)], ['Type', kindText(l)], ['Area', `${num(l.area_mm2, 0)} mm²`], ['Visible in result', seen(l)],
        ...(pictureLayer(l) ? [['Image', picture(l)]] : [])]),
      search: (l) => I18N.name(l.name),
      filters: [{key: 'kind', label: 'Type', options: Object.entries(KIND), test: (l, v) => l.kind === v}],
      sorts: [['order', 'Layer order', (a, b) => a.index - b.index], ['area', 'Largest area', (a, b) => b.area_mm2 - a.area_mm2],
        ['hidden', 'Least visible', (a, b) => (a.engraves ? a.visible_percent : -1) - (b.engraves ? b.visible_percent : -1)]]}).el;
  }

  /** The composition card of check.composition; null when the file fills nothing. ``key``: the photograph, for the list's choices. */
  function card(check, key) {
    const c = check && check.composition;
    if (!c) return null;
    const s = c.share, photoLayers = c.layers.filter((l) => l.kind === 'photo' || l.kind === 'depth');
    const ignored = photoLayers.filter((l) => l.ignored_shapes);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Work composition'),
      h('p', {}, verdict(c)),
      h('div', {class: 'comp-bar', role: 'img', 'aria-label': `fill ${pct(s.fill_only)}, photo ${pct(s.photo_only)}, both layers ${pct(s.both)}`},
        segment('fill', s.fill_only, 'fill only'), segment('both', s.both, 'fill and photo'), segment('photo', s.photo_only, 'photo only')),
      h('p', {class: 'small muted'}, `Fill ${pct(s.fill_only)} · photo ${pct(s.photo_only)} · both layers ${pct(s.both)} · marked ${num(c.marked_mm2, 0)} mm²`
        + (c.cleaning_layer != null ? ' (the cleaning plate is not counted as a color).' : '.')),
      layerList(c.layers, key),
      ignored.length ? h('p', {class: 'small muted'}, ignored.map((l) => `Layer ${l.name} also contains ${l.ignored_shapes} ordinary shapes (frame, outlines): `
        + 'only images are engraved on an image layer, not shapes (assumption: the Joker file has a frame around the image, while the photograph shows flat fill colors inside it).').join(' ')) : null,
      photoLayers.some((l) => l.family === 'dots' || l.family === 'edges') ? h('p', {class: 'small muted'},
        'Raster images engrave dots with the underlying layer visible between them. An area is considered covered when dots occupy at least 5% (assumption).') : null);
  }

  /** Notes on sample coverage and color variation for a measured layer. */
  function layerNotes(l) {
    const out = [];
    (l.covered_by || []).forEach((p) => out.push(h('span', {}, `Under the image on layer ${p.name} (${PhotoModes.label(p.mode)}): ${pct(p.percent)} of the sample`
      + (p.dot_density_percent != null ? `; dots cover ${pct(p.dot_density_percent)} on average, mixing with the fill color; excluded from measurement` : '; this layer scans every pixel, so the color belongs to it') + '.')));
    if (l.spread) out.push(h('span', {class: 'muted'}, `Color variation in the sample: L* ±${num(l.spread.L, 1)} (5–95%: ${num(l.spread.L_range[0], 0)}–${num(l.spread.L_range[1], 0)}), chroma ±${num(l.spread.chroma, 1)}.`));
    return out;
  }

  return {card, layerNotes};
})();
