/* Векторная работа из фотографии, шаг «Цвета» (REQ-042, DEC-073..DEC-077): каждому исходному цвету — измеренный цвет титана
   этого лазера, линзы и заготовки. Автоматически берётся самый быстрый цвет в пределах допуска ΔE; если такого нет, ближайший
   только предлагается, и цвет остаётся нерешённым, пока оператор не примет замену, не выберет другой цвет или не исключит его.
   Цвета, снятые без привязки к эталону, автоматика не берёт, пока их не включить; вручную их выбрать можно. Цвет меняется
   для всей группы или для одной области (щелчок по области на картинке в цветах титана). Автоматическая перекраска даёт
   варианты; любой можно вернуть, последнее действие — отменить. */
'use strict';
const VectorColours = (() => {
  const {h, fill, btn, field, get, post, pill, fail, modal, table, num, labText} = App;
  const NS = 'http://www.w3.org/2000/svg';
  const MODES = [['closest', 'Ближе к оригиналу'], ['tonality', 'Сохранить тональность'], ['random', 'Случайно'], ['fewer_layers', 'Меньше слоёв']];
  const MODE = Object.fromEntries(MODES);
  const BASIS = {chart: 'по карте', clean: 'по чистому титану', 'as-shot': 'как снято, без привязки'};
  const STATUS = {automatic: ['подобран автоматически', 'ok'], hand: ['выбран вручную', 'ok'], accepted: ['замена принята', 'ok'],
    proposed: ['предложен: вне допуска', 'bad'], missing: ['нет цвета титана', 'bad'], excluded: ['исключён', '']};
  const HOW = {fastest_within_tolerance: 'самый быстрый в пределах допуска', nearest: 'ближайший', tonality: 'по тональности', random: 'случайно',
    cover: 'общий слой', nearest_outside_tolerance: 'ближайший, вне допуска', kept: 'выбор оператора', hand: 'выбор оператора'};
  const EXCLUDED = '#e6e6e6';                 // исключённое не гравируется: остаётся только чистка
  const svgCache = new Map();
  const paletteCache = new Map();
  const rgb = (c) => `rgb(${c[0]},${c[1]},${c[2]})`;
  const chip = (c, title) => h('span', {class: 'sw', style: `background:${rgb(c)}`, title: title || ''});
  const params = (p) => `${num(p.power, 1)} % · ${num(p.frequency, 1)} кГц · ${num(p.speed, 0)} мм/с · Q-Pulse ${num(p.pulse_width, 0)} нс`
    + (p.line_interval == null ? '' : ` · шаг ${num(p.line_interval, 3)} мм`) + ` · ${p.passes ?? 1} проход(а)` + (p.cross_hatch ? ' · cross-hatch' : '');
  const stability = (e) => (e.stability && e.stability.assessed ? 'дисперсия ' + num(e.stability.variance) : 'не оценено');
  const seconds = (s) => (s == null ? 'не оценено' : num(s, 1) + ' с/см²');

  /** Разбиение в исходных цветах (SVG) один раз на версию документа: геометрия не приходит с каждым ответом. */
  async function splitSvg(j) {
    const key = `${j.id}:${j.document.version}`;
    if (!svgCache.has(key)) {
      const res = await fetch(`/api/vector/${j.id}/split.svg`);
      if (!res.ok) throw new Error('Разбиение не загрузилось');
      svgCache.set(key, await res.text());
    }
    const doc = new DOMParser().parseFromString(svgCache.get(key), 'image/svg+xml');
    const svg = document.importNode(doc.documentElement, true);
    svg.removeAttribute('width'); svg.removeAttribute('height');
    svg.setAttribute('class', 'vw-preview');
    return svg;
  }

  async function palette(j) {
    if (!paletteCache.has(j.id)) paletteCache.set(j.id, get(`/vector/${j.id}/palette`));
    try { return await paletteCache.get(j.id); } catch (e) { paletteCache.delete(j.id); throw e; }
  }

  /** Цвет титана каждой области: свой цвет области, иначе цвет её группы; исключённое — светло-серое, нерешённое — штриховка. */
  function recolour(svg, j) {
    const colours = Object.fromEntries(j.colours.map((c) => [String(c.index), c]));
    const exColours = new Set(j.colouring.excluded_colours.map(String)), exRegions = new Set(j.colouring.excluded_regions);
    const defs = document.createElementNS(NS, 'defs');
    const step = Math.max(j.document.size_mm.width, j.document.size_mm.height) / 80;
    for (const c of j.colours.filter((x) => x.status === 'proposed' || x.status === 'missing')) {
      const p = document.createElementNS(NS, 'pattern');
      for (const [k, v] of Object.entries({id: `vw-open-${j.id}-${c.index}`, patternUnits: 'userSpaceOnUse', width: step, height: step, patternTransform: 'rotate(45)'})) p.setAttribute(k, v);
      const bg = document.createElementNS(NS, 'rect');
      for (const [k, v] of Object.entries({width: step, height: step, fill: c.entry_id ? rgb(j.entries[c.entry_id].srgb) : '#ffffff'})) bg.setAttribute(k, v);
      const line = document.createElementNS(NS, 'rect');
      for (const [k, v] of Object.entries({width: step / 3, height: step, fill: '#d32f2f'})) line.setAttribute(k, v);
      p.append(bg, line);
      defs.append(p);
    }
    svg.prepend(defs);
    for (const path of svg.querySelectorAll('path[data-region]')) {
      const id = path.getAttribute('data-region'), c = colours[path.getAttribute('data-color')];
      const own = j.colouring.regions[id];
      let paint, open = false;
      if (exRegions.has(id)) paint = EXCLUDED;
      else if (own) [paint, open] = j.entries[own] ? [rgb(j.entries[own].srgb), false] : ['#ffffff', true];   // its colour left the palette
      else if (exColours.has(String(c.index))) paint = EXCLUDED;
      else if (c.status === 'proposed' || c.status === 'missing') [paint, open] = [`url(#vw-open-${j.id}-${c.index})`, true];
      else paint = rgb(j.entries[c.entry_id].srgb);
      path.setAttribute('fill', paint);
      path.setAttribute('stroke', open ? '#d32f2f' : paint);
    }
    return svg;
  }

  /** Выбор цвета титана из палитры: ближайшие к исходному цвету первыми; снятые без привязки — бледные с пунктиром. */
  async function pick(j, title, sourceLab, current, onPick) {
    let entries;
    try { entries = await palette(j); } catch (e) { return fail(e); }
    const de = (e) => Math.hypot(e.lab[0] - sourceLab[0], e.lab[1] - sourceLab[1], e.lab[2] - sourceLab[2]);
    const sorted = [...entries].sort((a, b) => de(a) - de(b));
    let chosen = sorted.find((e) => e.id === current) || null;
    const detail = h('div', {class: 'small'});
    const show = () => fill(detail, chosen ? [chip(chosen.srgb), labText(chosen.lab), ` · ΔE ${num(de(chosen))} · ${BASIS[chosen.basis]} · `,
      `гравировок ${chosen.engravings}, фото ${chosen.photographs} · ${seconds(chosen.time_s_per_cm2)}`, h('div', {class: 'muted'}, params(chosen.parameters)),
      chosen.automatic ? null : h('div', {class: 'muted'}, 'Этот цвет автоматика не выбирает (снят без привязки или медленнее предела времени); выбрать вручную можно.')]
      : h('span', {class: 'muted'}, 'Выберите цвет'));
    const grid = h('div', {class: 'vw-swatches', role: 'listbox', 'aria-label': 'Измеренные цвета титана'}, sorted.map((e) => h('button', {type: 'button',
      class: 'vw-swatch' + (e.basis === 'as-shot' ? ' as-shot' : '') + (e.id === current ? ' picked' : ''), style: `background:${rgb(e.srgb)}`,
      title: `${labText(e.lab)} · ΔE ${num(de(e))} · ${seconds(e.time_s_per_cm2)}`, 'aria-label': `ΔE ${num(de(e))}`,
      onClick: (ev) => { chosen = e; grid.querySelectorAll('.picked').forEach((x) => x.classList.remove('picked')); ev.target.classList.add('picked'); show(); }})));
    show();
    modal(title, h('div', {class: 'stack'}, h('p', {class: 'muted small'}, `Все измеренные цвета этого лазера, линзы и титана: ${entries.length}. Ближайшие к исходному цвету — первыми.`),
      grid, detail), [{label: 'Отмена', run: (m) => m.close()},
      {label: 'Применить', cls: 'primary', run: async (m) => { if (!chosen) return; m.close(); await onPick(chosen.id); }}]);
  }

  function regionDialog(j, region, c, run) {
    const own = j.colouring.regions[region];
    const excluded = j.colouring.excluded_regions.includes(region);
    const current = own || c.entry_id;
    const m = modal(`Область ${region}`, h('div', {class: 'stack'},
      h('p', {}, chip(c.srgb), `Исходный цвет № ${c.index + 1}`, ' · ', current && j.entries[current] ? [chip(j.entries[current].srgb), own ? 'свой цвет области' : 'цвет группы'] : 'цвета титана нет'),
      excluded ? h('p', {class: 'muted small'}, 'Область исключена: в файл не попадёт, останется только чистка.') : null), [
      {label: 'Цвет этой области', run: (x) => { x.close(); return pick(j, `Цвет области ${region}`, c.lab, current, (id) => run({op: 'set_region', region, entry_id: id})); }},
      {label: 'Цвет всей группы', run: (x) => { x.close(); return pick(j, `Цвет группы № ${c.index + 1}`, c.lab, c.entry_id, (id) => run({op: 'set_colour', colour: c.index, entry_id: id})); }},
      own ? {label: 'Вернуть цвет группы', run: async (x) => { x.close(); await run({op: 'set_region', region, entry_id: null}); }} : null,
      {label: excluded ? 'Вернуть область' : 'Исключить область', run: async (x) => { x.close(); await run({op: excluded ? 'include_region' : 'exclude_region', region}); }},
    ].filter(Boolean));
    return m;
  }

  /** Сводка нерешённого: сколько цветов, областей и какая доля площади; сами цвета — по «показать». */
  function unresolved(j, run) {
    const u = j.unresolved;
    if (!u.colours && !u.missing_regions) return null;
    const items = j.colours.filter((c) => u.indexes.includes(c.index));
    const list = h('div', {class: 'stack', hidden: true}, items.map((c) => h('div', {class: 'row'}, chip(c.srgb), `№ ${c.index + 1}`,
      c.entry_id ? [' → ', chip(j.entries[c.entry_id].srgb), `предложен, ΔE ${num(c.delta_e)}`] : ' — цвета титана нет',
      c.entry_id ? btn('Принять', () => run({op: 'accept', colour: c.index})) : null, btn('Исключить', () => run({op: 'exclude_colour', colour: c.index})))));
    const toggle = btn('показать', () => { list.hidden = !list.hidden; toggle.textContent = list.hidden ? 'показать' : 'скрыть'; });
    return h('div', {class: 'alert bad stack'}, h('div', {class: 'row'},
      h('span', {}, u.colours ? `Не решено: цветов ${u.colours}, областей ${u.regions} (${num(u.share * 100, 1)} % площади) — в допуске ΔE ${j.settings.tolerance_de} нет цвета титана. ` : '',
        u.missing_regions ? `Областей с цветом, которого больше нет в палитре: ${u.missing_regions}. ` : '', 'Пока это не решено, файл LightBurn не создаётся.'),
      u.colours ? toggle : null, items.some((c) => c.entry_id) ? btn('Принять все предложенные', () => run({op: 'accept_all'})) : null), list);
  }

  function colourRows(j, run) {
    return j.colours.map((c) => {
      const e = c.entry_id ? j.entries[c.entry_id] : null;
      const [label, kind] = STATUS[c.status];
      const actions = [btn('Изменить', () => pick(j, `Цвет группы № ${c.index + 1}`, c.lab, c.entry_id, (id) => run({op: 'set_colour', colour: c.index, entry_id: id})))];
      if (c.status === 'proposed') actions.push(btn('Принять', () => run({op: 'accept', colour: c.index})));
      if (c.status === 'hand' || c.status === 'accepted') actions.push(btn('Автоматически', () => run({op: 'set_colour', colour: c.index, entry_id: null})));
      actions.push(c.status === 'excluded' ? btn('Вернуть', () => run({op: 'include_colour', colour: c.index})) : btn('Исключить', () => run({op: 'exclude_colour', colour: c.index})));
      return [h('span', {}, chip(c.srgb, labText(c.lab)), `№ ${c.index + 1}`, h('div', {class: 'muted small'}, `областей ${c.regions}`)),
        h('span', {}, e ? chip(e.srgb, labText(e.lab)) : '—', pill(label, kind), c.how && HOW[c.how] ? h('div', {class: 'muted small'}, HOW[c.how]) : null),
        e ? h('span', {class: 'small'}, params(e.parameters)) : '—', e ? BASIS[e.basis] : '—',
        e ? `${e.engravings} / ${e.photographs}` : '—', c.delta_e == null ? '—' : num(c.delta_e),
        e ? (e.confidence == null ? 'не оценено' : num(e.confidence)) : '—', e ? stability(e) : '—', e ? seconds(e.time_s_per_cm2) : '—',
        h('span', {class: 'row'}, actions)];
    });
  }

  function variants(j, run) {
    const rows = [...j.variants].reverse().map((v) => [`№ ${v.number}`, MODE[v.mode] + (v.mode === 'random' ? ` (вариант ${v.seed})` : ''),
      `${v.totals.recipes}`, num(v.totals.mean_delta_e), `${v.totals.within_tolerance} из ${v.totals.colours}`,
      v.totals.seconds == null ? 'не оценено' : Math.round(v.totals.seconds) + ' с', v.at.replace('T', ' ').slice(0, 16),
      v.number === j.colouring.variant ? pill('текущий', 'ok') : btn('Вернуть', () => run({op: 'restore', variant: v.number}))]);
    return table(['Вариант', 'Способ', 'Рецептов', 'Средний ΔE', 'Цветов в допуске', 'Время слоёв цвета', 'Когда', ''], rows);
  }

  /** Карточка шага: допуск и фильтры, автоматическая перекраска, сводка нерешённого, три картинки рядом, цвета и варианты. */
  function card(j, run) {
    const s = j.settings;
    const tol = h('input', {type: 'number', step: 'any', min: '0', value: s.tolerance_de, 'aria-label': 'Допуск ΔE'});
    const maxTime = h('input', {type: 'number', step: 'any', min: '0', value: s.max_time ?? '', placeholder: 'без предела', 'aria-label': 'Наибольшее время, с/см²'});
    const asShot = h('input', {type: 'checkbox', checked: s.include_as_shot});
    const original = h('figure', {}, h('img', {src: `/api/plans/${j.id}/source-image`, alt: 'Исходная картинка', class: 'vw-image'}), h('figcaption', {class: 'muted small'}, 'Оригинал'));
    const split = h('figure', {}, h('p', {class: 'muted small'}, 'Загрузка…'), h('figcaption', {class: 'muted small'}, 'Разбиение в исходных цветах'));
    const titanium = h('figure', {}, h('p', {class: 'muted small'}, 'Загрузка…'),
      h('figcaption', {class: 'muted small'}, 'В цветах титана; нерешённые заштрихованы красным, исключённые — светло-серые. Щёлкните по области, чтобы выбрать ей цвет.'));
    const colours = Object.fromEntries(j.colours.map((c) => [String(c.index), c]));
    splitSvg(j).then((svg) => {
      fill(split, svg, split.lastChild);
      const tinted = recolour(svg.cloneNode(true), j);
      tinted.addEventListener('click', (ev) => {
        const path = ev.target.closest('path[data-region]');
        if (path) regionDialog(j, path.getAttribute('data-region'), colours[path.getAttribute('data-color')], run);
      });
      fill(titanium, tinted, titanium.lastChild);
    }).catch((e) => fill(split, h('p', {class: 'alert bad'}, e.message)));
    return h('div', {class: 'card stack'}, h('h3', {}, '2. Цвета'),
      h('p', {class: 'muted small'}, `Палитра — все измеренные цвета этого лазера, линзы и титана (${j.palette_size}). Автоматически берётся самый быстрый `
        + 'по времени гравировки цвет в пределах допуска ΔE; если такого нет, ближайший только предлагается.'),
      j.palette_size ? null : h('div', {class: 'alert warn'}, 'Для этого лазера, линзы и титана нет измеренных цветов заливки: раскрасить нечем.'),
      h('div', {class: 'toolbar'}, field('Допуск ΔE', tol), field('Наибольшее время, с/см²', maxTime),
        h('label', {class: 'row'}, asShot, h('span', {}, 'Включить цвета без привязки (сняты без эталона)')),
        btn('Применить', () => run({op: 'settings', tolerance_de: tol.value === '' ? null : +tol.value, max_time: maxTime.value === '' ? null : +maxTime.value,
          include_as_shot: asShot.checked}))),
      h('div', {class: 'row'}, h('span', {class: 'muted small'}, 'Перекрасить автоматически:'), MODES.map(([mode, label]) => btn(label, () => run({op: 'assign', mode}))),
        j.undo ? btn('Отменить последнее действие', () => run({op: 'undo'})) : null),
      unresolved(j, run),
      h('div', {class: 'grid g3 vw-previews'}, original, split, titanium),
      h('p', {class: 'small'}, `Рецептов: ${j.totals.recipes} из ${j.layer_cap} · средний ΔE ${num(j.totals.mean_delta_e)} · цветов в допуске ${j.totals.within_tolerance} из ${j.totals.colours}`),
      table(['Исходный цвет', 'Цвет титана', 'Рецепт', 'Как измерен', 'Гравировок / фото', 'ΔE', 'Уверенность', 'Стабильность', 'Время', ''], colourRows(j, run)),
      h('h3', {}, 'Варианты раскраски'), variants(j, run));
  }

  return {card, splitSvg, recolour};
})();
