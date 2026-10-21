/* Состав работы (REQ-053, DEC-095): из чего сделан файл — заливки, фотогравировка или то и другое, сколько площади видно в итоге,
   чем накрыта проба слоя. Строится по файлу, до фотографии; проверка накладывает на него фото. */
'use strict';
const Composition = (() => {
  const {h, num, table} = App;
  const KIND = {cleaning: 'очистка плиты', fill: 'заливка', photo: 'фотогравировка', depth: 'глубина (3D-слайс)'};
  const pct = (v) => (v == null ? '—' : `${num(v, 1)}%`);

  function verdict(c) {
    const s = c.share, photo = c.layers.some((l) => l.kind === 'photo' || l.kind === 'depth'), fills = c.layers.some((l) => l.kind === 'fill');
    if (c.mixed && c.picture_over_fills) return `Фотогравировка наложена поверх заливок на ${pct(s.both)} рабочей площади: цвет заливок под ней — смесь с её точками.`;
    if (c.mixed) return `Смешанная работа: заливки (${pct(s.fill_only)}) и фотогравировка (${pct(s.photo_only)}) лежат рядом, картинка вырезана там, где заливки; под обоими слоями только ${pct(s.both)}.`;
    if (photo) return 'Только фотогравировка' + (c.cleaning_layer != null ? ' на очищенной плите.' : '.');
    return fills ? 'Только векторные заливки.' : 'Слоёв, которые что-то гравируют площадью, нет.';
  }

  const segment = (cls, v, text) => (v ? h('span', {class: 'comp-' + cls, style: `width:${v}%`, title: `${text} ${pct(v)}`}) : null);

  /** Карточка состава работы по check.composition; null, если файл ничего не заполняет. */
  function card(check) {
    const c = check && check.composition;
    if (!c) return null;
    const s = c.share, photoLayers = c.layers.filter((l) => l.kind === 'photo' || l.kind === 'depth');
    const rows = c.layers.map((l) => [h('strong', {}, I18N.name(l.name)),
      KIND[l.kind] + (l.mode ? ` · ${PhotoModes.label(l.mode)}` : '') + (l.hidden ? ' · скрыт' : ''),
      num(l.area_mm2, 0), l.engraves ? pct(l.visible_percent) : 'вывод выключен',
      l.kind === 'photo' || l.kind === 'depth' ? [`картинка непрозрачна на ${pct(l.opaque_percent)}`, `гравирует ${pct(l.struck_percent)}`,
        l.dot_density_percent != null ? `точки в среднем ${pct(l.dot_density_percent)} площади` : null].filter(Boolean).join(' · ') : '']);
    const ignored = photoLayers.filter((l) => l.ignored_shapes);
    return h('div', {class: 'card stack'}, h('h3', {}, 'Состав работы'),
      h('p', {}, verdict(c)),
      h('div', {class: 'comp-bar', role: 'img', 'aria-label': `заливка ${pct(s.fill_only)}, фото ${pct(s.photo_only)}, оба слоя ${pct(s.both)}`},
        segment('fill', s.fill_only, 'только заливка'), segment('both', s.both, 'заливка и фото'), segment('photo', s.photo_only, 'только фото')),
      h('p', {class: 'small muted'}, `Заливка ${pct(s.fill_only)} · фото ${pct(s.photo_only)} · оба слоя ${pct(s.both)} · размечено ${num(c.marked_mm2, 0)} мм²`
        + (c.cleaning_layer != null ? ' (плита очистки не считается цветом).' : '.')),
      table(['Слой', 'Что это', 'Площадь, мм²', 'Видно в итоге', 'Картинка'], rows, null, true),
      ignored.length ? h('p', {class: 'small muted'}, ignored.map((l) => `На слое ${l.name} есть ещё ${l.ignored_shapes} обычных фигур (рамка, контуры): `
        + 'на слое-изображении гравируются только картинки, фигуры не гравируются (допущение; в файле Joker рамка вокруг картинки, а на фото внутри неё плоские цвета заливок).').join(' ')) : null,
      photoLayers.some((l) => l.family === 'dots' || l.family === 'edges') ? h('p', {class: 'small muted'},
        'Растровая картинка бьёт точками: между ними виден слой под ней. Место с точками считается накрытым, если точки занимают не меньше 5% площади (допущение).') : null);
  }

  /** Строки о слое для карточки измеренного слоя: чем накрыта проба и насколько цвет неровный. */
  function layerNotes(l) {
    const out = [];
    (l.covered_by || []).forEach((p) => out.push(h('span', {}, `Под картинкой слоя ${p.name} (${PhotoModes.label(p.mode)}): ${pct(p.percent)} пробы`
      + (p.dot_density_percent != null ? `; точки в среднем ${pct(p.dot_density_percent)} площади, цвет там — смесь заливки с точками, в измерение не входит` : '; такой слой сканирует каждый пиксель, цвет там принадлежит ему') + '.')));
    if (l.spread) out.push(h('span', {class: 'muted'}, `Разброс цвета в пробе: L* ±${num(l.spread.L, 1)} (5–95%: ${num(l.spread.L_range[0], 0)}–${num(l.spread.L_range[1], 0)}), цветность ±${num(l.spread.chroma, 1)}.`));
    return out;
  }

  return {card, layerNotes};
})();
