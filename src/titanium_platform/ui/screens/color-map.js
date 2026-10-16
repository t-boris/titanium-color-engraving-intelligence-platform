/* Общая карта цветов (REQ-029, DEC-056): все измеренные цвета всех экспериментов на одном экране.
   Нужен цвет: выбираете его, и видно, где он встречался и какими настройками получен. По экспериментам ходить не нужно. */
'use strict';
const ColorMap = (() => {
  const {h, btn, link, pill, get, num, swatch, labText} = App;
  const SVG = 'http://www.w3.org/2000/svg';
  const KIND = {calibrated: ['по эталонной карте', 'ok'], relative: ['относительно камеры', 'warn']};

  // sRGB (#rrggbb) -> Lab (D65), как в приложении
  function hexToLab(hex) {
    const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
    const X = (0.4124564 * c[0] + 0.3575761 * c[1] + 0.1804375 * c[2]) / 0.95047, Y = 0.2126729 * c[0] + 0.7151522 * c[1] + 0.072175 * c[2],
      Z = (0.0193339 * c[0] + 0.119192 * c[1] + 0.9503041 * c[2]) / 1.08883;
    const f = (t) => (t > 216 / 24389 ? Math.cbrt(t) : (24389 / 27 * t + 16) / 116);
    return [116 * f(Y) - 16, 500 * (f(X) - f(Y)), 200 * (f(Y) - f(Z))];
  }
  const settings = (p) => [p.power == null ? null : `${num(p.power, 1)}%`, p.frequency == null ? null : `${num(p.frequency, 0)} кГц`,
    p.speed == null ? null : `${num(p.speed, 0)} мм/с`, p.pulse_width == null ? 'Q-Pulse нет в файле' : `${num(p.pulse_width, 0)} нс`,
    p.line_interval == null ? null : `шаг ${num(p.line_interval, 4)} мм`, p.passes == null ? null : `${p.passes} проход(а)`].filter(Boolean).join(' · ');
  const when = (iso) => (iso || '').slice(0, 10);
  const colours = (n) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'цвет' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'цвета' : 'цветов'}`;
  const times = (n) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'раз' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'раза' : 'раз'}`;

  function plot(points, onPick, target, picked) {
    if (!points.length) return h('p', {class: 'muted'}, 'Нет цветов под такие условия.');
    const W = 640, H = 460, pad = 34;
    const a = points.map((p) => p.display_lab[1]).concat(target ? [target[1]] : []), b = points.map((p) => p.display_lab[2]).concat(target ? [target[2]] : []);
    const lo = [Math.min(...a, -4) - 4, Math.min(...b, -4) - 4], hi = [Math.max(...a, 4) + 4, Math.max(...b, 4) + 4];
    const x = (v) => pad + ((v - lo[0]) / (hi[0] - lo[0])) * (W - 2 * pad), y = (v) => H - pad - ((v - lo[1]) / (hi[1] - lo[1])) * (H - 2 * pad);
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Карта измеренных цветов в плоскости a* и b*'); svg.style.cssText = 'width:100%;max-width:820px';
    const add = (tag, attrs, text) => { const el = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); if (text) el.textContent = text; svg.append(el); return el; };
    add('line', {x1: x(lo[0]), x2: x(hi[0]), y1: y(0), y2: y(0), stroke: '#44556e', 'stroke-width': 1});
    add('line', {x1: x(0), x2: x(0), y1: y(lo[1]), y2: y(hi[1]), stroke: '#44556e', 'stroke-width': 1});
    add('text', {x: W - pad, y: y(0) - 6, fill: '#9fb0c8', 'font-size': 12, 'text-anchor': 'end'}, 'a*  красный →');
    add('text', {x: x(0) + 8, y: pad - 10, fill: '#9fb0c8', 'font-size': 12}, 'b*  жёлтый ↑');
    points.slice().sort((p, q) => q.display_lab[0] - p.display_lab[0]).forEach((p) => {
      const c = add('circle', {cx: x(p.display_lab[1]), cy: y(p.display_lab[2]), r: picked && picked.id === p.id ? 10 : 7,
        fill: swatch(p.display_lab).style.background || '#888', stroke: picked && picked.id === p.id ? '#ffffff' : p.measurement === 'calibrated' ? '#dfe7f5' : '#7d8aa3',
        'stroke-width': picked && picked.id === p.id ? 3 : 1.4, 'stroke-dasharray': p.approximate ? '3 2' : '', style: 'cursor:pointer'});
      c.append(Object.assign(document.createElementNS(SVG, 'title'), {textContent: `${p.title} · ${p.layer_name || 'слой ' + p.layer_index} · ${labText(p.display_lab)}`}));
      c.addEventListener('click', () => onPick(p));
    });
    if (target) { add('circle', {cx: x(target[1]), cy: y(target[2]), r: 13, fill: 'none', stroke: '#ffd166', 'stroke-width': 2.5});
      add('line', {x1: x(target[1]) - 18, x2: x(target[1]) + 18, y1: y(target[2]), y2: y(target[2]), stroke: '#ffd166', 'stroke-width': 1.5});
      add('line', {x1: x(target[1]), x2: x(target[1]), y1: y(target[2]) - 18, y2: y(target[2]) + 18, stroke: '#ffd166', 'stroke-width': 1.5}); }
    return svg;
  }

  function where(p) {
    return h('div', {class: 'stack small'},
      h('p', {}, h('strong', {}, `${p.layer_name || 'слой ' + p.layer_index}`), ' · ', link('/experiment/' + encodeURIComponent(p.experiment), p.title),
        ' · ', link(`/analysis/${p.pair_id}`, 'разбор измерений')),
      h('p', {class: 'muted'}, [p.setup, p.material, `фото ${p.photo}`, when(p.date)].filter(Boolean).join(' · ')),
      h('p', {}, settings(p.parameters)));
  }

  async function render(ctx) {
    const state = JSON.parse(sessionStorage.getItem('color-map') || '{}');
    const f = {setup: state.setup || '', material: state.material || '', measurement: state.measurement || '', unreferenced: !!state.unreferenced};
    const q = new URLSearchParams();
    if (f.setup) q.set('setup', f.setup);
    if (f.material) q.set('material', f.material);
    if (f.measurement) q.set('measurement', f.measurement);
    if (f.unreferenced) q.set('include_unreferenced', 'true');
    const [data, profiles] = await Promise.all([get('/colors' + (q.toString() ? '?' + q : '')), get('/profiles')]);
    const remember = (patch) => { sessionStorage.setItem('color-map', JSON.stringify({...f, ...patch})); App.render({preserveScroll: true}); };
    const select = (label, key, values, current, names) => h('label', {class: 'f'}, h('span', {}, label),
      h('select', {onChange: (e) => remember({[key]: e.target.value})}, h('option', {value: ''}, 'Все'),
        ...values.map((v) => h('option', {value: v, selected: v === current}, names ? names[v] : v))));

    let target = state.target || null, picked = null;
    const results = h('div', {class: 'stack'}), detail = h('div', {class: 'card stack', hidden: true}), plotBox = h('div', {});
    const drawPlot = () => plotBox.replaceChildren(plot(data.points, (p) => { picked = p; detail.hidden = false;
      detail.replaceChildren(h('h3', {}, 'Выбранный цвет'), h('div', {class: 'row'}, swatch(p.display_lab),
        h('span', {}, `${labText(p.display_lab)}${p.approximate ? ' · условный оттенок' : ''}`), pill(...KIND[p.measurement])), where(p),
        btn('Найти такой же среди всех', () => { setTarget(p.display_lab); }, 'btn-small')); drawPlot(); }, target, picked));
    async function setTarget(lab) {
      target = lab.map((v) => +(+v).toFixed(1));
      L.value = target[0]; A.value = target[1]; B.value = target[2]; chip.replaceChildren(swatch(target));
      sessionStorage.setItem('color-map', JSON.stringify({...f, target}));
      const p = new URLSearchParams({L: target[0], a: target[1], b: target[2], limit: '12'});
      for (const k of ['setup', 'material', 'measurement']) if (f[k]) p.set(k, f[k]);
      if (f.unreferenced) p.set('include_unreferenced', 'true');
      const r = await get('/colors/search?' + p);
      drawPlot();
      results.replaceChildren(h('h3', {}, 'Где встречался такой цвет'),
        !r.matches.length ? h('p', {class: 'muted'}, 'Подходящих цветов пока нет.') : h('div', {class: 'stack'}, ...r.matches.map((m) => h('article', {class: 'card stack color-hit'},
          h('div', {class: 'row'}, swatch(m.display_lab), h('strong', {}, `ΔE ${num(m.distance, 1)}`), pill(...KIND[m.measurement]),
            m.approximate ? pill('условный оттенок', 'warn') : null, h('span', {class: 'muted small'}, m.repeats > 1 ? `получался ${times(m.repeats)} в ${m.experiments.length} экспериментах` : 'получен один раз')),
          where(m)))));
    }
    const picker = h('input', {type: 'color', value: '#7a5a34', 'aria-label': 'Нужный цвет', onInput: (e) => setTarget(hexToLab(e.target.value))});
    const L = h('input', {type: 'number', step: 'any', min: 0, max: 100, value: target ? target[0] : 40, 'aria-label': 'L'});
    const A = h('input', {type: 'number', step: 'any', value: target ? target[1] : 5, 'aria-label': 'a'});
    const B = h('input', {type: 'number', step: 'any', value: target ? target[2] : 15, 'aria-label': 'b'});
    const chip = h('span', {});
    const find = btn('Найти', () => setTarget([+L.value, +A.value, +B.value]), 'primary');
    drawPlot();
    if (target) setTarget(target);

    const unrefNote = data.counts.unreferenced && !f.unreferenced
      ? h('div', {class: 'alert warn'}, `${colours(data.counts.unreferenced)} не показано на карте: у их снимков нет эталонной карты и нет чистой поверхности для сравнения. `,
        btn('Показать всё равно', () => remember({unreferenced: true}), 'btn-small')) : null;
    const total = data.points.length;
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Карта цветов'),
        h('p', {class: 'sub'}, 'Все измеренные цвета всех экспериментов. Выберите нужный цвет и увидите, где он встречался и какими настройками получен.')), h('span', {class: 'spacer'}),
        profiles.length ? link('/colors?profile=' + profiles[profiles.length - 1].id, 'Модель и прогноз параметров по версии профиля') : null),
      h('div', {class: 'card stack'}, h('div', {class: 'toolbar'},
        select('Лазер и линза', 'setup', data.options.setups, f.setup), select('Материал', 'material', data.options.materials, f.material),
        select('Как измерен', 'measurement', ['calibrated', 'relative'], f.measurement, {calibrated: 'По эталонной карте', relative: 'Относительно камеры'}),
        h('label', {class: 'row small'}, h('input', {type: 'checkbox', checked: f.unreferenced, onChange: (e) => remember({unreferenced: e.target.checked})}),
          'Показывать цвета без чистой поверхности')),
        h('p', {class: 'muted small'}, `Показано цветов: ${total} · по эталонной карте ${data.counts.calibrated} · относительно камеры ${data.counts.relative}. `
          + 'Цвета без эталонной карты приведены к чистому титану того же снимка: так их можно сравнивать между снимками, но оттенок условный (пунктирный контур).')),
      unrefNote,
      h('div', {class: 'color-map-grid'},
        h('div', {class: 'card stack'}, h('h3', {}, 'Карта a* × b*'), plotBox, detail),
        h('div', {class: 'card stack'}, h('h3', {}, 'Какой цвет нужен'),
          h('div', {class: 'row'}, picker, chip), h('div', {class: 'grid g3'}, h('label', {class: 'f'}, h('span', {}, 'L (0–100)'), L), h('label', {class: 'f'}, h('span', {}, 'a'), A),
            h('label', {class: 'f'}, h('span', {}, 'b'), B)), find,
          h('p', {class: 'muted small'}, 'Выберите цвет на палитре или введите L, a, b. Можно также нажать на любой цвет на карте и «Найти такой же среди всех».'), results)));
  }
  return {render, hexToLab};
})();
