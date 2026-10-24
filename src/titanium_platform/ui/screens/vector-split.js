/* Векторная работа из фотографии, разбиение (REQ-042, DEC-074, DEC-076; выбор алгоритма и общий раздел с цветами — фича
   vector-detail-and-colour-control, DEC-076): алгоритм, число цветов, плотность, сглаживание, лица — всё на виду, как
   часть раздела «Цвета и разбиение» (vector-colours.js). Найденные важные области (лицо, глаза, губы) нарисованы поверх
   картинки в сворачиваемом блоке: оператор убирает найденную область или добавляет свою — тянет прямоугольник или эллипс
   по картинке (координаты — пиксели рабочей картинки). Изменения областей и настроек применяются кнопкой «Разбить заново»:
   разбиение пересчитывается, раскраска начинается заново. */
/* vector-detail-and-colour-control: the density is a slider beside the number of regions it would give, counted by the server before the
   split (I-2, its DEC-093). An eye, the lips and a marked area have a detail of their own, a marked area its kind (eye, lips, other), and
   any area's boundary can be moved or drawn again (I-3, its DEC-094); when only the detail, boundary or kind of areas changed, the colours
   outside the changed areas stay as they were after «Разбить заново». */
'use strict';
const VectorSplit = (() => {
  const {h, fill, btn, field, post, fail, toast, confirmBox} = App;
  const NS = 'http://www.w3.org/2000/svg';
  const DENSITY = {min: 30, max: 250, step: 5};                     // vector_job.DENSITY
  const LEVELS = {coarse: 70, medium: 100, fine: 150};                // the former levels of detail, points of the same scale
  const KIND = {face: 'Лицо', eye: 'Глаз', lips: 'Губы', manual: 'Отмечено вручную'};
  const FINE = ['eye', 'lips', 'manual'];                                            // faces.FINE_KINDS: these have a detail of their own
  const DETAILS = [['fine', 'мелко'], ['finer', 'очень мелко'], ['finest', 'максимально'], ['face', 'как у лица']];   // faces.DETAILS
  const MARKED = [['eye', 'глаз'], ['lips', 'губы'], ['manual', 'другое']];           // vector_job.MARKED_KINDS
  /** Алгоритмы разбиения и чем они отличаются: что получается на картинке и сколько это стоит (DEC-082 фичи
      vector-detail-and-colour-control; числа — портрет работы 22 на 1200 пикселях, 28 цветов, крупно, с лицами и без). Детальность — не алгоритм:
      она есть у каждого. Ключ метода хранится в работе: SLIC — «Мозаика», как и раньше. */
  const ALGORITHMS = [
    ['slic', 'Мозаика', 'Универсальный, по умолчанию. Картинка делится на ровные участки близкого размера: лица и мягкие переходы держит лучше всего, границы плавные. Считается быстро: около 1,5 секунды на портрете в 1200 пикселей.'],
    ['tonal', 'По тонам', 'Области повторяют свет и тень: брови, губы, блик на носу, складки — отдельными пятнами, а не участками сетки. Самый подробный по светотени. Считается дольше остальных: около 3 секунд на портрете в 1200 пикселей.'],
    ['planes', 'Крупные плоскости', 'Большие ровные плоскости одного тона и полосы вдоль линий, участков одинакового размера нет. Областей примерно на 40 % меньше, чем у «Мозаики»: рисунок проще, тонкие переходы тона пропадают. В лицах, глазах и губах области остаются мельче.'],
    ['seeds', 'SEEDS', 'Близок к «Мозаике»: те же ровные участки, но считается быстрее (около секунды), и областей чуть меньше. Тонкие линии и текст держит не хуже, особенно на шумных и неровно освещённых снимках. На портретах границы чуть грубее, а ошибка цвета чуть больше.']];
  const RESET = 'Области будут найдены заново, и раскраска начнётся сначала: цвета, выбранные вручную, варианты раскраски и шаги отмены этого разбиения '
    + 'пропадут. Надписи и фотозоны перенесутся на новое разбиение. Прежние файлы LightBurn и результаты гравировок останутся.';
  const algorithmName = (v) => (ALGORITHMS.find(([id]) => id === v) || ALGORITHMS[0])[1];

  /** Выбор алгоритма с пояснением, для каким картинкам он подходит; пояснение меняется вместе с выбором. */
  function picker(current) {
    const select = h('select', {'aria-label': 'Алгоритм разбиения'}, ALGORITHMS.map(([v, name]) => h('option', {value: v, selected: v === current}, name)));
    const hint = h('p', {class: 'toolbar-hint'});
    const explain = () => fill(hint, h('strong', {}, algorithmName(select.value) + ': '), (ALGORITHMS.find(([id]) => id === select.value) || ALGORITHMS[0])[2]);
    select.addEventListener('change', explain);
    explain();
    return {select, hint};
  }
  /** Гладкость границ — ползунок в мм (0: как найдены): каждое движение перерисовывает границы сразу, разбиение и цвета остаются
      (REQ-052, DEC-083). Запросы идут по одному: пока один считается, берётся последнее положение, промежуточные пропускаются. */
  function smoothness(j, apply) {
    const input = h('input', {type: 'range', min: '0', max: String(j.smoothing_max_mm || 2), step: '0.05', value: String(j.smoothing_mm || 0),
      'aria-label': 'Гладкость линий, мм'});
    const say = (v) => (+v === 0 ? 'как найдены' : `${App.num(+v, 2)} мм`);
    const readout = h('output', {class: 'vw-slider-value'}, say(input.value));
    let sent = +input.value, busy = false, timer = null;
    async function pump() {
      if (busy) return;
      busy = true;
      try {
        while (+input.value !== sent) { sent = +input.value; await apply(sent); }
      } catch (e) { fail(e); sent = +input.value; } finally { busy = false; }
    }
    input.addEventListener('input', () => { readout.textContent = say(input.value); clearTimeout(timer); timer = setTimeout(pump, 120); });
    return h('div', {class: 'vw-slider'}, input, readout);
  }
  /** The density (I-2): how many coarse superpixels lie along the picture's longer side, apart from the number of colours. The server counts
      the regions it would give with the same settings, the work unchanged (``count``); one request at a time, for the last position. */
  function densityControl(j, settings) {
    const s = j.split, start = s.density || LEVELS[s.detail] || LEVELS.medium;
    const input = h('input', {type: 'range', min: String(DENSITY.min), max: String(DENSITY.max), step: String(DENSITY.step), value: String(start),
      'aria-label': 'Плотность областей'});
    const readout = h('output', {class: 'vw-slider-value'}, String(start));
    const count = h('p', {class: 'small vw-density-count'}, `сейчас областей: ${j.document.regions}`);
    let asked = null, busy = false, timer = null;
    async function pump() {
      if (busy) return;
      busy = true;
      try {
        while (JSON.stringify(settings()) !== asked) {
          asked = JSON.stringify(settings());
          fill(count, 'считаю, сколько будет областей…');
          const r = await post(`/vector/${j.id}/split/preview`, settings());
          if (JSON.stringify(settings()) === asked) fill(count, `будет областей: ${r.regions} (сейчас ${j.document.regions}) · наименьшая ${App.num(r.min_area_mm2, 2)} мм²`);
        }
      } catch (e) { fail(e); fill(count, `сейчас областей: ${j.document.regions}`); asked = null; } finally { busy = false; }
    }
    const recount = () => { clearTimeout(timer); timer = setTimeout(pump, 400); };
    input.addEventListener('input', () => { readout.textContent = input.value; recount(); });
    return {input, count, recount, el: h('div', {class: 'vw-slider'}, input, readout)};
  }
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };

  /** An area's boundary alone: an ellipse or a polygon. */
  const outline = (a) => (a.ellipse ? {ellipse: a.ellipse} : {polygon: a.polygon});
  /** An area moved by (dx, dy) pixels. */
  function moved(a, dx, dy) {
    if (a.ellipse) return {ellipse: {...a.ellipse, center: [a.ellipse.center[0] + dx, a.ellipse.center[1] + dy]}};
    return {polygon: a.polygon.map(([x, y]) => [x + dx, y + dy])};
  }
  /** Whether a point lies inside an area (a turned ellipse or a polygon). */
  function inside(a, [x, y]) {
    if (a.ellipse) {
      const e = a.ellipse, t = -(e.angle || 0) * Math.PI / 180, dx = x - e.center[0], dy = y - e.center[1];
      const u = dx * Math.cos(t) - dy * Math.sin(t), v = dx * Math.sin(t) + dy * Math.cos(t);
      return (u / e.axes[0]) ** 2 + (v / e.axes[1]) ** 2 <= 1;
    }
    let hit = false;
    const p = a.polygon;
    for (let i = 0, k = p.length - 1; i < p.length; k = i++) {
      if ((p[i][1] > y) !== (p[k][1] > y) && x < (p[k][0] - p[i][0]) * (y - p[i][1]) / (p[k][1] - p[i][1]) + p[i][0]) hit = !hit;
    }
    return hit;
  }
  /** A detected area's changes in one form, to compare them with the saved ones. */
  const norm = (c) => ({number: c.number, detail: c.detail || null, ellipse: c.ellipse || null, polygon: c.polygon || null});

  /** Фигура области в пикселях картинки: эллипс или многоугольник. */
  function shape(area, cls) {
    if (area.ellipse) {
      const e = area.ellipse;
      return svgEl('ellipse', {cx: e.center[0], cy: e.center[1], rx: e.axes[0], ry: e.axes[1], transform: `rotate(${e.angle || 0} ${e.center[0]} ${e.center[1]})`, class: cls});
    }
    return svgEl('polygon', {points: area.polygon.map((p) => p.join(',')).join(' '), class: cls});
  }

  /** Блок разбиения в разделе «Цвета и разбиение»: настройки с выбором алгоритма, счётчики, «Разбить заново» и, в
      сворачиваемом блоке, картинка с важными областями. */
  function card(j, reload, smooth) {
    const doc = j.document, s = j.split;
    const W = doc.image_px.width, H = doc.image_px.height;
    const manual = s.manual.map((a) => ({...a}));
    const removed = new Set(s.removed);
    const adjusted = new Map((s.adjusted || []).map((c) => [c.number, {...c}]));   // detected areas with the operator's detail or boundary
    let editing = null;                                                           // the area whose boundary is edited: {found: number} or {manual: index}
    const colours = h('input', {type: 'number', step: '1', min: '2', max: String(j.layer_cap), value: s.n_colors, 'aria-label': 'Число цветов'});
    const algorithm = picker(s.algorithm || 'slic');
    const settings = () => ({n_colors: +colours.value, algorithm: algorithm.select.value, density: +density.input.value, faces: faces.checked,
      manual, removed: [...removed], adjusted: [...adjusted.values()].sort((a, b) => a.number - b.number)});
    /** A detected area as the split will use it: with the operator's detail and boundary. */
    const effective = (a) => {
      const c = adjusted.get(a.number) || {};
      return {...a, ...(c.ellipse || c.polygon ? {ellipse: undefined, polygon: undefined, ...outline(c)} : {}), detail: c.detail};
    };
    const adjust = (number, change) => {
      const c = {number, ...(adjusted.get(number) || {}), ...change};
      if (!c.detail || c.detail === 'fine') delete c.detail;
      if (c.detail || c.ellipse || c.polygon) adjusted.set(number, c); else adjusted.delete(number);
    };
    const edited = () => (editing == null ? null : 'found' in editing ? effective(j.areas.detected[editing.found]) : manual[editing.manual]);
    const reshape = (area) => {
      if ('found' in editing) adjust(editing.found, {ellipse: undefined, polygon: undefined, ...area});
      else manual[editing.manual] = {...manual[editing.manual], ellipse: undefined, polygon: undefined, ...area};
      for (const a of [adjusted.get(editing.found), manual[editing.manual]]) {
        if (a) for (const k of ['ellipse', 'polygon']) if (a[k] === undefined) delete a[k];
      }
    };
    const density = densityControl(j, settings);
    const smoothing = smoothness(j, smooth || (async () => {}));
    const faces = h('input', {type: 'checkbox', checked: s.faces});
    const tool = h('select', {'aria-label': 'Форма новой области'}, h('option', {value: 'rect'}, 'Прямоугольник'), h('option', {value: 'ellipse'}, 'Эллипс'));
    const overlay = svgEl('svg', {viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', class: 'vw-areas', role: 'img',
      'aria-label': 'Важные области поверх картинки; тяните, чтобы отметить свою'});
    const list = h('div', {class: 'stack'});
    const pending = h('p', {class: 'muted small', hidden: true}, 'Изменения областей применятся после «Разбить заново».');
    const editHint = h('p', {class: 'small', hidden: true});
    const areasTitle = h('summary', {});
    let areasKey = null;                                               // the areas as last drawn: a change of them recounts the regions

    /** An area's detail, one of four; a face has none of its own. */
    const detailPicker = (value, set) => {
      const select = h('select', {'aria-label': 'Детальность области'}, DETAILS.map(([v, l]) => h('option', {value: v, selected: v === (value || 'fine')}, l)));
      select.addEventListener('change', () => { set(select.value); draw(); });
      return select;
    };
    const isEditing = (which) => editing != null && JSON.stringify(editing) === JSON.stringify(which);
    const borderButton = (which) => btn(isEditing(which) ? 'Готово' : 'Граница', () => { editing = isEditing(which) ? null : which; draw(); });

    function draw() {
      const key = JSON.stringify([manual, [...removed].sort(), faces.checked, settings().adjusted]);
      if (areasKey !== null && key !== areasKey) density.recount();
      areasKey = key;
      if (editing && (('found' in editing && (!faces.checked || removed.has(editing.found))) || ('manual' in editing && !manual[editing.manual]))) editing = null;
      overlay.replaceChildren();
      j.areas.detected.forEach((a) => {
        if (!faces.checked) return;
        overlay.append(shape(effective(a), (removed.has(a.number) ? 'vw-area removed' : 'vw-area ' + a.kind) + (isEditing({found: a.number}) ? ' editing' : '')));
      });
      manual.forEach((a, i) => overlay.append(shape(a, 'vw-area manual' + (isEditing({manual: i}) ? ' editing' : ''))));
      const was = JSON.stringify((s.adjusted || []).map(norm)), now = JSON.stringify(settings().adjusted.map(norm));
      const changed = JSON.stringify(manual) !== JSON.stringify(s.manual) || removed.size !== s.removed.length
        || [...removed].some((n) => !s.removed.includes(n)) || was !== now;
      pending.hidden = !changed;
      editHint.hidden = editing == null;
      fill(editHint, 'Тяните внутри выделенной области, чтобы сдвинуть её, или рядом с ней, чтобы нарисовать её границу заново (форма — как у новой области). «Готово» — закончить.');
      fill(areasTitle, `Важные области: лица, глаза, губы и отмеченные вручную (найдено ${faces.checked ? j.areas.detected.length : 0}, отмечено ${manual.length}, убрано ${removed.size})`);
      const rows = (faces.checked ? j.areas.detected : []).map((a) => {
        const gone = removed.has(a.number), changedHere = adjusted.has(a.number);
        return h('div', {class: 'row'},
          h('span', {}, `${KIND[a.kind]} · найдено`, a.score == null ? '' : ` (оценка ${App.num(a.score)})`, gone ? ' · убрано' : changedHere ? ' · изменено' : ''),
          !gone && FINE.includes(a.kind) ? detailPicker(effective(a).detail, (v) => adjust(a.number, {detail: v})) : null,
          !gone ? borderButton({found: a.number}) : null,
          !gone && changedHere ? btn('Как найдено', () => { adjusted.delete(a.number); draw(); }) : null,
          gone ? btn('Вернуть', () => { removed.delete(a.number); draw(); }) : btn('Убрать', () => { removed.add(a.number); draw(); }));
      });
      manual.forEach((a, i) => {
        const kind = h('select', {'aria-label': 'Что это за область'}, MARKED.map(([v, l]) => h('option', {value: v, selected: v === (a.kind || 'manual')}, l)));
        kind.addEventListener('change', () => { manual[i] = {...manual[i], kind: kind.value}; draw(); });
        rows.push(h('div', {class: 'row'}, h('span', {}, `Отмечено вручную № ${i + 1}`), kind,
          detailPicker(a.detail, (v) => { manual[i] = {...manual[i], detail: v === 'fine' ? undefined : v}; if (!manual[i].detail) delete manual[i].detail; }),
          borderButton({manual: i}),
          btn('Убрать', () => { manual.splice(i, 1); if (editing && 'manual' in editing) editing = null; draw(); })));
      });
      fill(list, rows.length ? rows : h('p', {class: 'muted small'}, 'Важных областей нет. Потяните по картинке, чтобы отметить свою.'));
    }

    // dragging on the picture: a rectangle or an ellipse in pixels of the working picture, a new area or the edited area's new boundary;
    // dragging inside the edited area moves its boundary
    let start = null, ghost = null, grabbed = null;
    const at = (ev) => {
      const r = overlay.getBoundingClientRect();
      return [Math.min(W, Math.max(0, (ev.clientX - r.left) / r.width * W)), Math.min(H, Math.max(0, (ev.clientY - r.top) / r.height * H))];
    };
    const areaOf = (a, b) => {
      const [x0, x1] = [Math.min(a[0], b[0]), Math.max(a[0], b[0])], [y0, y1] = [Math.min(a[1], b[1]), Math.max(a[1], b[1])];
      if (x1 - x0 < 2 || y1 - y0 < 2) return null;
      return tool.value === 'ellipse' ? {ellipse: {center: [(x0 + x1) / 2, (y0 + y1) / 2], axes: [(x1 - x0) / 2, (y1 - y0) / 2], angle: 0}}
        : {polygon: [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]};
    };
    const drawn = (p) => {
      if (!grabbed) return areaOf(start, p);
      const [dx, dy] = [p[0] - start[0], p[1] - start[1]];
      return dx || dy ? moved(grabbed, dx, dy) : null;
    };
    overlay.addEventListener('pointerdown', (ev) => {
      start = at(ev);
      const area = edited();
      grabbed = area && inside(area, start) ? outline(area) : null;
      overlay.setPointerCapture(ev.pointerId); ev.preventDefault();
    });
    overlay.addEventListener('pointermove', (ev) => {
      if (!start) return;
      const area = drawn(at(ev));
      if (ghost) ghost.remove();
      ghost = area ? shape(area, 'vw-area manual editing') : null;
      if (ghost) overlay.append(ghost);
    });
    overlay.addEventListener('pointerup', (ev) => {
      if (!start) return;
      const area = drawn(at(ev));
      start = null; grabbed = null;
      if (ghost) { ghost.remove(); ghost = null; }
      if (!area) return;
      if (editing) reshape(area); else manual.push(area);
      draw();
    });
    faces.addEventListener('change', draw);
    for (const el of [colours, algorithm.select]) el.addEventListener('change', () => density.recount());
    draw();

    // split again: the colouring, its variants and its undo steps start anew, so the operator is asked first (I-8)
    const run = btn('Разбить заново', () => confirmBox('Разбить картинку заново?', RESET, 'Разбить заново', async () => {
      try {
        await post(`/vector/${j.id}/split`, settings());
        toast('Картинка разбита заново; цвета подобраны заново', 'ok');
        reload();
      } catch (e) { fail(e); }
    }), 'primary');
    const found = !doc.faces.searched ? 'поиск лиц выключен' : j.areas.search_failed ? 'поиск лиц не удался — отметьте важные области вручную'
      : doc.faces.found ? `лиц найдено: ${doc.faces.found}` : 'лицо не найдено';
    return h('div', {class: 'stack vw-split'}, h('h4', {}, 'Разбиение'),
      h('div', {class: 'vw-split-fields'}, field('Алгоритм разбиения', algorithm.select),
        field('Число цветов', colours, `2–${j.layer_cap}: чистка — первый слой` + (j.markers_enabled ? ', ещё один — маркеры' : '')),
        field('Плотность областей', density.el, 'меньше — крупнее и меньше областей, больше — мелче; 70, 100 и 150 — прежние «крупно», «средне» и «детально»'),
        field('Гладкость линий', smoothing, 'ползунок перерисовывает границы сразу; области и цвета не меняются')),
      density.count,
      h('div', {class: 'vw-split-actions'}, h('label', {class: 'row'}, faces, h('span', {}, 'Искать лица (глаза и губы — подробнее)')), run),
      algorithm.hint,
      h('p', {class: 'small'}, `Алгоритм ${algorithmName(doc.algorithm)} · цветов: ${doc.colours} · областей: ${doc.regions} · ${found}` + (doc.important_regions ? ` · областей в важных местах: ${doc.important_regions}` : '')
        + ` · наименьшая область ${App.num(doc.min_area_mm2, 2)} мм²`),
      h('details', {class: 'vw-details vw-areas-box'}, areasTitle,
        h('div', {class: 'grid g2'},
          h('figure', {}, h('div', {class: 'vw-stage'}, h('img', {src: `/api/plans/${j.id}/source-image`, alt: 'Исходная картинка'}), overlay),
            h('figcaption', {class: 'muted small'}, 'Картинка делится на цветные области без зазоров: общая граница двух областей — одна линия; лица, глаза, губы и отмеченные области делятся мельче. ',
              'Лицо — голубое, глаза и губы — жёлтые, отмеченные вручную — зелёные, убранные — пунктир, выделенная — толще. Потяните по картинке, чтобы отметить свою область. ',
              'У глаза, губ и отмеченной области своя детальность; если изменить только её, границу или вид области, цвета вне изменённых областей после «Разбить заново» останутся прежними.')),
          h('div', {class: 'stack'}, field('Новая область', tool), list, editHint, pending))));
  }

  return {card, ALGORITHMS, picker, name: algorithmName};
})();
