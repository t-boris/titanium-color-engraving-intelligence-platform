/* Общая карта цветов (REQ-029, DEC-056): все измеренные цвета всех экспериментов на одном экране.
   Нужен цвет: выбираете его, и видно, где он встречался и какими настройками получен. По экспериментам ходить не нужно. */
'use strict';
const ColorMap = (() => {
  const {h, fill, btn, link, pill, get, num, swatch, labText} = App;
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

  // the three planes of Lab: which coordinate goes right and which goes up
  const PLANES = {ab: {x: 1, y: 2, right: 'a*  красный →', up: 'b*  жёлтый ↑', zero: true}, La: {x: 1, y: 0, right: 'a*  красный →', up: 'L*  светлее ↑', zero: false},
    Lb: {x: 2, y: 0, right: 'b*  жёлтый →', up: 'L*  светлее ↑', zero: false}};

  function plot(points, onPick, target, picked, plane, spiral) {
    if (!points.length) return h('p', {class: 'muted'}, 'Нет цветов под такие условия.');
    const P = PLANES[plane] || PLANES.ab;
    const W = 640, H = 460, pad = 34;
    const xs = points.map((p) => p.display_lab[P.x]).concat(target ? [target[P.x]] : []), ys = points.map((p) => p.display_lab[P.y]).concat(target ? [target[P.y]] : []);
    const lo = [Math.min(...xs, P.zero ? -4 : Infinity) - 4, Math.min(...ys, P.zero ? -4 : Infinity) - 4], hi = [Math.max(...xs, P.zero ? 4 : -Infinity) + 4, Math.max(...ys, P.zero ? 4 : -Infinity) + 4];
    const x = (v) => pad + ((v - lo[0]) / (hi[0] - lo[0])) * (W - 2 * pad), y = (v) => H - pad - ((v - lo[1]) / (hi[1] - lo[1])) * (H - 2 * pad);
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`); svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `Карта измеренных цветов: ${P.right} и ${P.up}`); svg.style.cssText = 'width:100%;max-width:820px';
    const add = (tag, attrs, text) => { const el = document.createElementNS(SVG, tag); for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v); if (text) el.textContent = text; svg.append(el); return el; };
    if (P.zero) { add('line', {x1: x(lo[0]), x2: x(hi[0]), y1: y(0), y2: y(0), stroke: '#44556e', 'stroke-width': 1});
      add('line', {x1: x(0), x2: x(0), y1: y(lo[1]), y2: y(hi[1]), stroke: '#44556e', 'stroke-width': 1}); }
    add('text', {x: W - pad, y: H - pad + 16, fill: '#9fb0c8', 'font-size': 12, 'text-anchor': 'end'}, P.right);
    add('text', {x: pad, y: pad - 10, fill: '#9fb0c8', 'font-size': 12}, P.up);
    if (spiral && spiral.length) {           // the film model: colour against the oxide thickness, drawn under the points
      const inside = (l) => l[P.x] >= lo[0] && l[P.x] <= hi[0] && l[P.y] >= lo[1] && l[P.y] <= hi[1];
      let d = '';
      spiral.forEach((s, i) => { const l = s.lab; d += (i && inside(l) && inside(spiral[i - 1].lab) ? 'L' : 'M') + `${x(l[P.x]).toFixed(1)} ${y(l[P.y]).toFixed(1)} `; });
      add('path', {d, fill: 'none', stroke: '#8fa3c4', 'stroke-width': 1.2, 'stroke-opacity': 0.7, 'stroke-dasharray': '4 3'});
      spiral.filter((s) => s.thickness_nm % 50 === 0 && inside(s.lab)).forEach((s) => {
        add('circle', {cx: x(s.lab[P.x]), cy: y(s.lab[P.y]), r: 2.5, fill: '#8fa3c4'});
        add('text', {x: x(s.lab[P.x]) + 5, y: y(s.lab[P.y]) - 4, fill: '#8fa3c4', 'font-size': 10}, `${s.thickness_nm} нм`); });
    }
    points.slice().sort((p, q) => q.display_lab[0] - p.display_lab[0]).forEach((p) => {
      const c = add('circle', {cx: x(p.display_lab[P.x]), cy: y(p.display_lab[P.y]), r: picked && picked.id === p.id ? 10 : 7,
        fill: swatch(p.display_lab).style.background || '#888', 'fill-opacity': p.referenced && !p.provisional ? 1 : 0.45,
        stroke: picked && picked.id === p.id ? '#ffffff' : p.provisional ? '#c9a2ff' : !p.referenced ? '#e0b050' : p.measurement === 'calibrated' ? '#dfe7f5' : '#7d8aa3',
        'stroke-width': picked && picked.id === p.id ? 3 : 1.4, 'stroke-dasharray': p.provisional ? '6 2 1 2' : !p.referenced ? '1.5 3' : p.approximate ? '3 2' : '', style: 'cursor:pointer'});
      c.append(Object.assign(document.createElementNS(SVG, 'title'), {textContent: `${p.title} · ${p.layer_name || 'слой ' + p.layer_index} · ${labText(p.display_lab)}${p.provisional ? ' · предварительно' : ''}`}));
      c.addEventListener('click', () => onPick(p));
    });
    if (target) { add('circle', {cx: x(target[P.x]), cy: y(target[P.y]), r: 13, fill: 'none', stroke: '#ffd166', 'stroke-width': 2.5});
      add('line', {x1: x(target[P.x]) - 18, x2: x(target[P.x]) + 18, y1: y(target[P.y]), y2: y(target[P.y]), stroke: '#ffd166', 'stroke-width': 1.5});
      add('line', {x1: x(target[P.x]), x2: x(target[P.x]), y1: y(target[P.y]) - 18, y2: y(target[P.y]) + 18, stroke: '#ffd166', 'stroke-width': 1.5}); }
    return svg;
  }

  // the film model's reading of one measured colour
  function filmOf(p, model) {
    if (!model) return null;
    const m = (model.points || []).find((q) => q.pair_id === p.pair_id && q.layer_index === p.layer_index);
    if (!m) return null;
    const alt = m.alternative ? ` или ${num(m.alternative.thickness_nm, 0)} нм (ΔE ${num(m.alternative.residual_de, 1)})` : '';
    return h('p', {class: 'small'}, h('strong', {}, 'Плёнка оксида по модели: '),
      m.thickness_determined ? `${num(m.thickness_nm, 0)} нм, расхождение ΔE ${num(m.residual_de, 1)}${m.ramp ? '; порядок интерференции выбран по всей пластине' : ''}`
        : m.dark_share >= 0.6 ? `в основном тёмный оксид (доля ${num(m.dark_share * 100, 0)} %), толщина плёнки по цвету не определяется`
        : `${num(m.thickness_nm, 0)} нм${alt}, расхождение ΔE ${num(m.residual_de, 1)}; порядок интерференции неоднозначен`,
      m.dark_share > 0 && m.dark_share < 0.6 ? ` · тёмного оксида ${num(m.dark_share * 100, 0)} %` : '');
  }

  /** Рассчитанная настройка показывается только с тремя оценками (REQ-002): уверенность, ожидаемая ошибка цвета, стабильность.
      Без них настройки нет, и сказано почему; остаются толщина плёнки и измеренные режимы. */
  function estimatesText(r) {
    const e = r.estimates;
    if (r.settings && e) {
      return ` · уверенность ${num(e.confidence, 2)} · ожидаемая ошибка цвета ΔE ${num(e.expected_delta_e, 1)}`
        + ` · стабильность: дисперсия ${num(e.stability.variance, 1)} по ${e.stability.cells} ближайшим ячейкам`;
    }
    return ` · настройка не рассчитана: ${I18N.tr(r.note || '')}`;
  }

  // what the film model says about a wanted colour; settings are computed only for one laser and lens (DEC-063)
  function filmCard(r) {
    const cand = (c) => h('article', {class: 'card stack'},
      h('p', {}, h('strong', {}, `Плёнка ${num(c.thickness_nm, 0)} нм`), c.dark_share > 0 ? ` с долей тёмного оксида ${num(c.dark_share * 100, 0)} %` : '', ` · расхождение с целью ΔE ${num(c.residual_de, 1)}`),
      (c.by_regime || []).length ? h('div', {class: 'stack small'}, h('span', {class: 'muted'}, 'Расчёт по закону толщины от дозы, не измерение; только в пределах измеренных доз режима:'),
        ...c.by_regime.map((r) => h('p', {}, h('strong', {}, `${num(r.frequency, 0)} кГц, ${num(r.pulse_width, 0)} нс`), `: около ${num(r.areal_energy_j_cm2, 0)} Дж/см²`,
          r.settings ? ` · ${settings(r.settings)}` : '',
          estimatesText(r),
          ' · ближайшая измеренная: ', swatch(r.nearest_measured.lab), ` ${r.nearest_measured.work} · ${r.nearest_measured.layer || ''}`))) : null,
      c.same_film_measured.length ? h('div', {class: 'stack small'}, h('span', {class: 'muted'}, 'Такую плёнку давали измеренные режимы:'),
        ...c.same_film_measured.map((m) => h('p', {}, swatch(m.lab), ` ${m.work} · ${m.layer || ''} · ${settings(m.parameters)} · плёнка ${num(m.thickness_nm, 0)} нм${m.ambiguous ? ' (порядок неоднозначен)' : ''}`,
          ' · ', link(`/analysis/${m.pair_id}`, 'разбор'))))
        : h('p', {class: 'muted small'}, 'Измеренных режимов с такой плёнкой пока нет.'));
    return h('div', {class: 'stack'}, h('h3', {}, 'Что говорит модель плёнки'),
      h('p', {class: 'small'}, r.reachable_by_a_film ? 'Цвет лежит на спирали интерференции: его даёт плёнка указанной толщины. Толщины ниже это измеренные режимы, а не расчёт.'
        : 'Цвет лежит вне спирали интерференции больше чем на 8 ΔE: по этой модели ни одна оксидная плёнка титана его не даёт.'),
      ...r.candidates.map(cand),
      h('p', {class: 'muted small'}, !r.partition ? 'Настройки по закону толщины от дозы рассчитываются только для одного лазера с одной линзой: выберите их в фильтре «Лазер и линза».'
        : r.kinetics.usable ? `Кинетика: закон толщины от дозы подогнан для режимов импульса: ${r.kinetics.regimes}.` : `Кинетика пока не даёт расчёта настроек: ${I18N.tr(r.kinetics.note)}.`));
  }

  function where(p) {
    // a provisional colour (DEC-045) comes from a check not accepted yet: its link leads to that check, not to an analysis
    return h('div', {class: 'stack small'},
      h('p', {}, h('strong', {}, `${p.layer_name || 'слой ' + p.layer_index}`), p.source === 'tonal' ? pill('серый → мощность') : null,
        Tasks.badge(p.task),
        p.provisional ? pill('предварительно', 'warn') : null, p.referenced ? null : pill('без привязки к чистому титану', 'warn'),
        ' · ', link('/experiment/' + encodeURIComponent(p.experiment), p.title),
        ' · ', p.provisional ? link(p.review, 'проверка пары: принять или исправить') : link(`/analysis/${p.pair_id}`, 'разбор измерений')),
      h('p', {class: 'muted'}, [p.setup_label, p.material, `фото ${p.photo}`, when(p.date)].filter(Boolean).join(' · ')),
      h('p', {}, settings(p.parameters)));
  }

  async function render(ctx) {
    const state = JSON.parse(sessionStorage.getItem('color-map') || '{}');
    const f = {setup: state.setup || '', material: state.material || '', measurement: state.measurement || '', task: state.task || '', hide: !!state.hide,
      within: !!state.within, provisional: !!state.provisional};
    const q = new URLSearchParams();
    if (f.setup) q.set('setup', f.setup);
    if (f.material) q.set('material', f.material);
    if (f.measurement) q.set('measurement', f.measurement);
    if (f.task) q.set('task', f.task);                 // REQ-020: цвета одной задачи гравировки
    if (f.hide) q.set('include_unreferenced', 'false');
    const data = await get('/colors' + (q.toString() ? '?' + q : ''));
    // the laser and lens chosen in the filter: the film model, its laws and computed settings are theirs alone
    const chosen = data.options.setups.find((o) => o.key === f.setup) || null;
    if (f.setup && !chosen) {                 // a filter remembered from before the laser and lens were keyed by their records
      sessionStorage.setItem('color-map', JSON.stringify({...state, setup: ''}));
      return render(ctx);
    }
    const partition = chosen ? `device_id=${chosen.device_id}&lens_id=${App.lensParam(chosen.lens_id)}` : '';
    const model = await get('/oxide/model' + (partition ? '?' + partition : '')).catch(() => null);
    const plane = state.plane || 'ab', band = state.band || [0, 100];
    const shown = () => data.points.filter((p) => p.display_lab[0] >= band[0] && p.display_lab[0] <= band[1]);
    const remember = (patch) => { sessionStorage.setItem('color-map', JSON.stringify({...f, target, plane, band, ...patch})); App.render({preserveScroll: true}); };
    const select = (label, key, values, current, names) => h('label', {class: 'f'}, h('span', {}, label),
      h('select', {onChange: (e) => remember({[key]: e.target.value})}, h('option', {value: ''}, 'Все'),
        ...values.map((v) => h('option', {value: v, selected: v === current}, names ? names[v] : v))));

    let target = state.target || null, picked = null;
    const results = h('div', {class: 'stack'}), detail = h('div', {class: 'card stack', hidden: true}), plotBox = h('div', {});
    const drawPlot = () => plotBox.replaceChildren(plot(shown(), (p) => { picked = p; detail.hidden = false;
      detail.replaceChildren(h('h3', {}, 'Выбранный цвет'), h('div', {class: 'row'}, swatch(p.display_lab),
        h('span', {}, `${labText(p.display_lab)}${p.approximate ? ' · условный оттенок' : ''}`), pill(...KIND[p.measurement]),
        p.referenced ? null : pill('как снято, без привязки', 'warn')), where(p), filmOf(p, model),
        btn('Найти такой же среди всех', () => { setTarget(p.display_lab); }, 'btn-small')); drawPlot(); }, target, picked, plane,
      model ? model.spiral : null));
    async function setTarget(lab) {
      target = lab.map((v) => +(+v).toFixed(1));
      L.value = target[0]; A.value = target[1]; B.value = target[2]; chip.replaceChildren(swatch(target));
      sessionStorage.setItem('color-map', JSON.stringify({...f, target}));
      const p = new URLSearchParams({L: target[0], a: target[1], b: target[2], limit: '12'});
      for (const k of ['setup', 'material', 'measurement', 'task']) if (f[k]) p.set(k, f[k]);
      if (f.within) p.set('include_unreferenced', 'true');
      if (f.provisional) p.set('include_provisional', 'true');
      const [r, film] = await Promise.all([get('/colors/search?' + p),
        get(`/colors/settings?L=${target[0]}&a=${target[1]}&b=${target[2]}${partition ? '&' + partition : ''}`).catch(() => null)]);
      drawPlot();
      // one entry per recipe: the same settings, laser and lens, titanium stock and kind of measurement; a re-photograph of one
      // engraving is not another repetition (DEC-021), so engravings and photographs are counted apart
      const often = (m) => (m.repeats > 1 ? `получался ${times(m.repeats)} (независимые гравировки)` : 'получен в одной гравировке')
        + ` · фото: ${m.photographs} · экспериментов: ${m.experiments.length}`;
      // REQ-020: измеренное свидетельство, не прогноз — наблюдения, повторяемость и чего не хватает в контексте
      const evidence = (m) => h('p', {class: 'muted small'},
        m.repeatability && m.repeatability.assessed ? `Повторяемость: независимые гравировки расходятся до ΔE ${num(m.repeatability.max_delta_e, 1)}`
          : 'Повторяемость не оценена: одна независимая гравировка',
        (m.observation_ids || []).length ? ` · наблюдения №${m.observation_ids.join(', №')}` : '',
        (m.provisional_checks || []).length ? ` · проверки на рассмотрении №${m.provisional_checks.join(', №')}` : '',
        ...(m.missing_context || []).length ? [' · не хватает: ', ...Tasks.missing(m.missing_context)] : []);
      fill(results, h('h3', {}, 'Где встречался такой цвет'), h('p', {class: 'muted small'}, 'Измерения, не прогноз: каждая запись — один рецепт одной задачи гравировки.'),
        !r.matches.length ? h('p', {class: 'muted'}, 'Подходящих цветов пока нет.') : h('div', {class: 'stack'}, ...r.matches.map((m) => h('article', {class: 'card stack color-hit'},
          h('div', {class: 'row'}, swatch(m.display_lab), h('strong', {}, `ΔE ${num(m.distance, 1)}`), pill(...KIND[m.measurement]),
            m.approximate ? pill(m.referenced ? 'к чистому титану, условный оттенок' : 'как снят, без привязки', 'warn') : null,
            m.provisional ? pill('предварительно', 'warn') : null,
            h('span', {class: 'muted small'}, often(m))),
          where(m), evidence(m)))),
        r.counts.unreferenced && !f.within ? h('div', {class: 'alert warn'}, `${colours(r.counts.unreferenced)} без привязки к чистому титану в поиске не участвуют: их расстояние до остальных ничего бы не значило. `,
          btn('Искать и среди них', () => remember({within: true}), 'btn-small')) : null,
        r.counts.provisional && !f.provisional ? h('div', {class: 'alert warn'}, `${colours(r.counts.provisional)} из проверок, которые ещё не приняты, в поиске не участвуют: они предварительные. `,
          btn('Искать и среди предварительных', () => remember({provisional: true}), 'btn-small')) : null,
        film ? h('div', {class: 'stack'}, pill('Прогноз модели, не измерение', 'warn'), filmCard(film)) : null);
    }
    const picker = h('input', {type: 'color', value: '#7a5a34', 'aria-label': 'Нужный цвет', onInput: (e) => setTarget(hexToLab(e.target.value))});
    const L = h('input', {type: 'number', step: 'any', min: 0, max: 100, value: target ? target[0] : 40, 'aria-label': 'L'});
    const A = h('input', {type: 'number', step: 'any', value: target ? target[1] : 5, 'aria-label': 'a'});
    const B = h('input', {type: 'number', step: 'any', value: target ? target[2] : 15, 'aria-label': 'b'});
    const chip = h('span', {});
    const find = btn('Найти', () => setTarget([+L.value, +A.value, +B.value]), 'primary');
    drawPlot();
    if (target) setTarget(target);

    const total = data.points.length;
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Карта цветов'),
        h('p', {class: 'sub'}, 'Все измеренные цвета всех экспериментов. Выберите нужный цвет и увидите, где он встречался и какими настройками получен.')), h('span', {class: 'spacer'}),
        chosen ? link(`/colors?device=${chosen.device_id}&lens=${App.lensParam(chosen.lens_id)}`, 'Модель и прогноз параметров для этого лазера с линзой')
          : h('span', {class: 'muted small'}, 'Выберите лазер и линзу, чтобы открыть их модель и прогноз')),
      h('div', {class: 'card stack'}, h('div', {class: 'toolbar'},
        select('Лазер и линза', 'setup', data.options.setups.map((o) => o.key), f.setup, Object.fromEntries(data.options.setups.map((o) => [o.key, o.label]))),
        select('Материал', 'material', data.options.materials, f.material),
        select('Как измерен', 'measurement', ['calibrated', 'relative'], f.measurement, {calibrated: 'По эталонной карте', relative: 'Относительно камеры'}),
        select('Задача', 'task', data.options.tasks || [], f.task, Object.fromEntries((data.options.tasks || []).map((k) => [k, Tasks.name(k)]))),
        h('label', {class: 'row small'}, h('input', {type: 'checkbox', checked: f.hide, onChange: (e) => remember({hide: e.target.checked})}),
          'Скрыть цвета без чистого титана на снимке')),
        h('p', {class: 'muted small'}, `Показано цветов: ${total} · по эталонной карте ${data.counts.calibrated} · относительно камеры ${data.counts.relative}`
          + (data.counts.unreferenced && !f.hide ? ` · из них без привязки к чистому титану ${data.counts.unreferenced}` : '')
          + (data.counts.provisional ? ` · предварительных (проверка ещё не принята) ${data.counts.provisional}` : '') + '. '
          + (data.counts.provisional ? 'Предварительные цвета обведены сиреневым штрихом и ведут к проверке пары; в прогнозы они не входят, а в поиск — только по отдельной просьбе, пока проверка не принята. ' : '')
          + 'Цвета без эталонной карты приведены к чистому титану того же снимка: так их можно сравнивать между снимками, но оттенок условный (пунктирный контур). '
          + 'Если на снимке нет чистого титана, цвет показан как снят (бледный кружок с точечным контуром) и в поиске по умолчанию не участвует.')),
      h('div', {class: 'color-map-grid'},
        h('div', {class: 'card stack'}, h('div', {class: 'row'}, h('h3', {}, 'Карта цветов'), h('span', {class: 'spacer'}),
            ...[['ab', 'a* × b*'], ['La', 'a* × L*'], ['Lb', 'b* × L*']].map(([k, label]) => btn(label, () => remember({plane: k}), plane === k ? 'primary btn-small' : 'btn-small'))),
          h('div', {class: 'row small'}, h('span', {}, 'Светлота L* от'),
            h('input', {type: 'number', min: 0, max: 100, value: band[0], style: 'width:5em', onChange: (e) => remember({band: [+e.target.value, band[1]]})}),
            h('span', {}, 'до'), h('input', {type: 'number', min: 0, max: 100, value: band[1], style: 'width:5em', onChange: (e) => remember({band: [band[0], +e.target.value]})}),
            h('span', {class: 'muted'}, ` · показано ${shown().length} из ${data.points.length}`),
            model && model.summary && model.summary.observations ? h('span', {class: 'muted'}, ` · пунктир: спираль плёнки оксида по модели (медиана расхождения ${num(model.summary.median_de_coloured, 1)} ΔE на ${model.summary.coloured} цветных)`) : null),
          plotBox, detail),
        h('div', {class: 'card stack'}, h('h3', {}, 'Какой цвет нужен'),
          h('div', {class: 'row'}, picker, chip), h('div', {class: 'grid g3'}, h('label', {class: 'f'}, h('span', {}, 'L (0–100)'), L), h('label', {class: 'f'}, h('span', {}, 'a'), A),
            h('label', {class: 'f'}, h('span', {}, 'b'), B)), find,
          h('p', {class: 'muted small'}, 'Выберите цвет на палитре или введите L, a, b. Можно также нажать на любой цвет на карте и «Найти такой же среди всех».'), results)));
  }
  return {render, hexToLab};
})();
