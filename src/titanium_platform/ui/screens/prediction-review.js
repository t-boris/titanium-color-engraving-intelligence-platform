/* Прогноз и результат (0.24.0, DEC-117): что шкала серого обещала для принятой фотогравировки до неё — по гравировкам, принятым раньше,
   на её ширине строк, как показывала работа, — и что вышло на фото: тон за тоном, медиана и максимум разницы, светлее или темнее, желтее
   или синее. Под этим — на чём стоял прогноз: ширина строк среди измеренных, пластины и их толщина, чистка, чистый титан на фото.
   Это факты с числами; ничего не взвешивается и не угадывается. Внизу — тот же итог по всем принятым фотогравировкам. */
'use strict';
const PredictionReview = (() => {
  const {h, fill, pill, get, swatch} = App;
  const value = (v, d = 1) => (v == null ? '—' : String(+(+v).toFixed(d)).replace('.', ','));
  const mm = (v) => `${value(v)} мм`;
  const plate = (p) => `${p.name || `пластина № ${p.id}`}${p.thickness_mm != null ? ` (${mm(p.thickness_mm)})` : ''}`;
  const cleaned = (c) => (c == null ? 'чистка не определена' : c ? 'по чистке' : 'без чистки');
  const HOW = {witness: 'свидетель чистки', lightest: 'самый светлый тон'};
  const reading = (r) => `${r.photo}: L* ${value(r.L)} (${HOW[r.how] || r.how})`;
  const lighter = (d) => `${d > 0 ? 'светлее' : 'темнее'} на ${value(Math.abs(d))} L*`;
  const REASON = {
    no_points: 'тона этого слоя не вошли в шкалу (связь серого с цветом слабая или картинка поверх заливок) — сравнивать нечего.',
    first: 'до неё на этих настройках ничего не было измерено — прогноза не было; теперь шкала этих настроек строится по ней.',
    kind: 'цвета до неё измерены иначе (с картой или без), чем эта фотография, — сравнивать нельзя.',
    outside: 'её мощности лежат вне измеренных до неё — на них прогноза не было.'};

  function sizeText(c) {
    if (c.how === 'measured') return [`Ширина строк ${mm(c.row_mm)} была измерена до неё.`, 'ok'];
    if (c.how === 'between') return [`Ширина строк ${mm(c.row_mm)} — между измеренными ${c.from_mm.map((v) => value(v)).join(' и ')} мм: прогноз взят между ними.`, ''];
    if (c.how === 'outside') {
      return [`Ширина строк ${mm(c.row_mm)} — вне измеренных до неё (${c.measured_mm.map((v) => value(v)).join('; ')} мм): прогноз взят с ближайшей, `
        + `${mm(c.from_mm[0])}, без пересчёта. На другой ширине строки остывают иначе, и та же мощность даёт другие цвета.`, 'warn'];
    }
    return ['Ширина строк не известна: прогноз — по всем измерениям этих настроек.', ''];
  }
  function plateText(c) {
    if (!c.differs) return [`Та же пластина: ${plate(c.own)}.`, 'ok'];
    return [`Прогноз — по гравировкам на ${c.used.map(plate).join(', ')}; эта — на ${plate(c.own)}.`, 'warn'];
  }
  function cleaningText(c) {
    const used = [...new Set(c.used.map((u) => cleaned(u.cleans)))].join(', ');
    if (c.own == null) return [`Чистка этой гравировки не определена; гравировки прогноза: ${used}.`, ''];
    if (!c.differs) return [`Чистка как у гравировок прогноза: ${cleaned(c.own)}.`, 'ok'];
    return [`Эта гравировка — ${cleaned(c.own)}; прогноз — по гравировкам ${used}.`, 'warn'];
  }
  function photoText(c) {
    if (!c.own) return ['Чистого титана на этом фото не видно: свет снимка не сравнить.', ''];
    const parts = [`Чистый титан на этом фото — ${reading(c.own)}.`];
    if (c.used.length) {
      const surface = c.used.every((r) => r.same_surface) && Math.abs(c.dL_used) >= 3 ? ' Пластина и чистка те же — это свет снимка, а не металл.' : '';
      parts.push(`На фото прогноза — ${c.used.map(reading).join('; ')}: это фото ${lighter(c.dL_used)}.${surface}`);
    }
    if (c.same_surface.length) {
      parts.push(`На той же пластине с той же чисткой — ${c.same_surface.map(reading).join('; ')}`
        + (Math.abs(c.dL_same) >= 3 ? `: это фото ${lighter(c.dL_same)} — это свет снимка, а не металл.` : ': свет снимков тот же.'));
    }
    return [parts.join(' '), c.differs ? 'warn' : 'ok'];
  }
  const CAUSE = {size: sizeText, plate: plateText, cleaning: cleaningText, photo: photoText};

  function shift(layer) {
    const dl = layer.median_dL, db = layer.median_db;
    const light = Math.abs(dl) < 1 ? 'по светлоте — как прогноз' : `${dl > 0 ? 'светлее' : 'темнее'} прогноза на ${value(Math.abs(dl))} L*`;
    const hue = Math.abs(db) < 3 ? '' : `, ${db > 0 ? 'желтее' : 'синее'} на ${value(Math.abs(db))} b*`;
    return `Вышло ${light}${hue} (медианы по тонам).`;
  }
  function tones(layer) {
    return h('details', {}, h('summary', {}, `Тона: прогноз и результат (${layer.bands.length})`),
      h('ul', {class: 'pr-tones'}, layer.bands.map((b) => h('li', {class: 'pr-tone'},
        h('span', {class: 'pr-power'}, `${value(b.power)} %`),
        h('span', {}, swatch(b.predicted), ` L* ${value(b.predicted[0], 0)}`), h('span', {class: 'muted'}, '→'),
        h('span', {}, swatch(b.lab), ` L* ${value(b.lab[0], 0)}`),
        pill(`${value(b.de)} ΔE`, b.de > layer.tolerance_de ? 'warn' : 'ok')))));
  }
  /** Слои без сравнения — одной строкой на причину: «Слои A, B: …», или «Прогноз: …», когда причина у всех слоёв одна. */
  function reasons(layers, all) {
    const by = new Map();
    for (const layer of layers) by.set(layer.reason, [...(by.get(layer.reason) || []), layer.name]);
    return [...by].map(([reason, names]) => h('p', {class: 'small muted'},
      `${names.length === all ? 'Прогноз' : `${names.length === 1 ? 'Слой' : 'Слои'} ${names.join(', ')}`}: ${REASON[reason] || reason}`));
  }
  function layerBlock(layer, several) {
    const name = several ? `Слой ${layer.name}: ` : '';
    const causes = layer.causes.map((c) => { const [text, kind] = CAUSE[c.code](c); return h('li', {class: kind ? `pr-${kind}` : ''}, text); });
    return h('div', {class: 'stack pr-layer'},
      h('div', {class: 'row'}, h('strong', {}, `${name}${name ? 'п' : 'П'}рогноз по ${layer.engravings} ${layer.engravings === 1 ? 'гравировке, принятой' : 'гравировкам, принятым'} раньше`),
        pill(`медиана ${value(layer.median_de)} ΔE`, layer.median_de > layer.tolerance_de ? 'warn' : 'ok')),
      h('p', {class: 'small'}, `Тонов сравнено: ${layer.compared} · максимум ${value(layer.max_de)} ΔE · в пределах ${value(layer.tolerance_de, 0)} ΔE: `
        + `${value(layer.within * 100, 0)} %. ${shift(layer)}`),
      h('h4', {}, 'На чём стоял прогноз'), h('ul', {class: 'pr-causes small'}, causes), tones(layer));
  }
  function overallText(o) {
    if (!o || !o.all.tones) return null;
    return h('p', {class: 'small muted'}, `По всем принятым фотогравировкам прогноз до них ошибался на ${value(o.all.median_de)} ΔE (медиана ${o.all.tones} тонов, `
      + `гравировок ${o.all.engravings}); где ширина была измерена заранее — ${o.size_measured.tones ? `${value(o.size_measured.median_de)} ΔE` : 'таких ещё нет'}.`);
  }

  /** Карточка разбора принятой фотографии (``review`` — ответ /pairs/<id>/prediction-review, ``overall`` — /prediction-reviews). */
  function card(review, overall) {
    if (!review.layers.length) return null;
    const several = review.layers.length > 1;
    return h('div', {class: 'stack pr-card'}, h('h3', {}, 'Прогноз и результат'),
      h('p', {class: 'small muted'}, 'Что шкала обещала до этой гравировки — по гравировкам, принятым раньше, на её ширине строк, как показывала работа, — и что вышло на фото.'),
      ...review.layers.filter((layer) => !layer.reason).map((layer) => layerBlock(layer, several)),
      ...reasons(review.layers.filter((layer) => layer.reason), review.layers.length), overallText(overall));
  }

  /** Загружает разбор принятой фотографии ``pairId`` в ``box``; ``still()`` — показана ли она ещё. */
  async function load(pairId, box, still) {
    try {
      const [review, overall] = await Promise.all([get(`/pairs/${pairId}/prediction-review`), get('/prediction-reviews')]);
      if (still()) fill(box, card(review, overall));
    } catch (e) {
      if (still()) fill(box, h('p', {class: 'small muted'}, `Прогноз и результат не сравнить: ${e.message}`));
    }
  }

  return {card, load};
})();
