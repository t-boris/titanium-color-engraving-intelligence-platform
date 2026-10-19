/* Векторная работа из фотографии, шаг «Разбиение» (REQ-042, DEC-074, DEC-076): число цветов, детальность, сглаживание,
   лица; найденные важные области (лицо, глаза, губы) нарисованы поверх картинки. Оператор убирает найденную область или
   добавляет свою — тянет прямоугольник или эллипс по картинке (координаты — пиксели рабочей картинки). Изменения областей
   и настроек применяются кнопкой «Разбить заново»: разбиение пересчитывается, раскраска начинается заново. */
'use strict';
const VectorSplit = (() => {
  const {h, fill, btn, field, post, fail, toast} = App;
  const NS = 'http://www.w3.org/2000/svg';
  const DETAIL = [['coarse', 'Крупно'], ['medium', 'Средне'], ['fine', 'Детально']];
  const KIND = {face: 'Лицо', eye: 'Глаз', lips: 'Губы', manual: 'Отмечено вручную'};
  const svgEl = (tag, attrs) => {
    const el = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
    return el;
  };

  /** Фигура области в пикселях картинки: эллипс или многоугольник. */
  function shape(area, cls) {
    if (area.ellipse) {
      const e = area.ellipse;
      return svgEl('ellipse', {cx: e.center[0], cy: e.center[1], rx: e.axes[0], ry: e.axes[1], transform: `rotate(${e.angle || 0} ${e.center[0]} ${e.center[1]})`, class: cls});
    }
    return svgEl('polygon', {points: area.polygon.map((p) => p.join(',')).join(' '), class: cls});
  }

  /** Карточка шага: настройки, картинка с важными областями, счётчики и «Разбить заново». */
  function card(j, reload) {
    const doc = j.document, s = j.split;
    const W = doc.image_px.width, H = doc.image_px.height;
    const manual = s.manual.map((a) => ({...a}));
    const removed = new Set(s.removed);
    const colours = h('input', {type: 'number', step: '1', min: '2', max: String(j.layer_cap), value: s.n_colors, 'aria-label': 'Число цветов'});
    const detail = h('select', {'aria-label': 'Детальность'}, DETAIL.map(([v, l]) => h('option', {value: v, selected: v === s.detail}, l)));
    const smoothing = h('input', {type: 'number', step: 'any', min: '0', value: s.tolerance_mm, 'aria-label': 'Сглаживание, мм'});
    const faces = h('input', {type: 'checkbox', checked: s.faces});
    const tool = h('select', {'aria-label': 'Форма новой области'}, h('option', {value: 'rect'}, 'Прямоугольник'), h('option', {value: 'ellipse'}, 'Эллипс'));
    const overlay = svgEl('svg', {viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: 'none', class: 'vw-areas', role: 'img',
      'aria-label': 'Важные области поверх картинки; тяните, чтобы отметить свою'});
    const list = h('div', {class: 'stack'});
    const pending = h('p', {class: 'muted small', hidden: true}, 'Изменения областей применятся после «Разбить заново».');

    function draw() {
      overlay.replaceChildren();
      j.areas.detected.forEach((a) => {
        if (!faces.checked) return;
        overlay.append(shape(a, removed.has(a.number) ? 'vw-area removed' : 'vw-area ' + a.kind));
      });
      manual.forEach((a) => overlay.append(shape(a, 'vw-area manual')));
      const changed = manual.length !== s.manual.length || removed.size !== s.removed.length || [...removed].some((n) => !s.removed.includes(n));
      pending.hidden = !changed;
      const rows = (faces.checked ? j.areas.detected : []).map((a) => h('div', {class: 'row'},
        h('span', {}, `${KIND[a.kind]} · найдено`, a.score == null ? '' : ` (оценка ${App.num(a.score)})`, removed.has(a.number) ? ' · убрано' : ''),
        removed.has(a.number) ? btn('Вернуть', () => { removed.delete(a.number); draw(); }) : btn('Убрать', () => { removed.add(a.number); draw(); })));
      manual.forEach((a, i) => rows.push(h('div', {class: 'row'}, h('span', {}, `${KIND.manual} № ${i + 1}`),
        btn('Убрать', () => { manual.splice(i, 1); draw(); }))));
      fill(list, rows.length ? rows : h('p', {class: 'muted small'}, 'Важных областей нет. Потяните по картинке, чтобы отметить свою.'));
    }

    // тянуть по картинке: прямоугольник или эллипс в пикселях рабочей картинки
    let start = null, ghost = null;
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
    overlay.addEventListener('pointerdown', (ev) => { start = at(ev); overlay.setPointerCapture(ev.pointerId); ev.preventDefault(); });
    overlay.addEventListener('pointermove', (ev) => {
      if (!start) return;
      const area = areaOf(start, at(ev));
      if (ghost) ghost.remove();
      ghost = area ? shape(area, 'vw-area manual') : null;
      if (ghost) overlay.append(ghost);
    });
    overlay.addEventListener('pointerup', (ev) => {
      if (!start) return;
      const area = areaOf(start, at(ev));
      start = null;
      if (ghost) { ghost.remove(); ghost = null; }
      if (area) { manual.push(area); draw(); }
    });
    faces.addEventListener('change', draw);
    draw();

    const run = btn('Разбить заново', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try {
        await post(`/vector/${j.id}/split`, {n_colors: +colours.value, detail: detail.value, tolerance_mm: +smoothing.value, faces: faces.checked,
          manual, removed: [...removed]});
        toast('Картинка разбита заново; цвета подобраны заново', 'ok');
        reload();
      } catch (e) { fail(e); self.disabled = false; }
    }, 'primary');
    const found = !doc.faces.searched ? 'поиск лиц выключен' : j.areas.search_failed ? 'поиск лиц не удался — отметьте важные области вручную'
      : doc.faces.found ? `лиц найдено: ${doc.faces.found}` : 'лицо не найдено';
    return h('div', {class: 'card stack'}, h('h3', {}, '1. Разбиение'),
      h('p', {class: 'muted small'}, 'Картинка делится на цветные области без зазоров: общая граница двух областей — одна линия. Лица, глаза, губы и отмеченные области делятся мельче.'),
      h('div', {class: 'toolbar'}, field('Число цветов', colours, `2–${j.layer_cap}: чистка — первый слой` + (j.markers_enabled ? ', ещё один — маркеры' : '')),
        field('Детальность', detail, 'крупно — спокойные большие области, детально — мелкие'), field('Сглаживание границ, мм', smoothing),
        h('label', {class: 'row'}, faces, h('span', {}, 'Искать лица (глаза и губы — подробнее)')), run),
      h('p', {class: 'small'}, `Цветов: ${doc.colours} · областей: ${doc.regions} · ${found}` + (doc.important_regions ? ` · областей в важных местах: ${doc.important_regions}` : '')
        + ` · наименьшая область ${App.num(doc.min_area_mm2, 2)} мм²`),
      h('div', {class: 'grid g2'},
        h('figure', {}, h('div', {class: 'vw-stage'}, h('img', {src: `/api/plans/${j.id}/source-image`, alt: 'Исходная картинка'}), overlay),
          h('figcaption', {class: 'muted small'}, 'Важные области: лицо — голубое, глаза и губы — жёлтые, отмеченные вручную — зелёные, убранные — пунктир. ',
            'Потяните по картинке, чтобы отметить свою область.')),
        h('div', {class: 'stack'}, field('Новая область', tool), list, pending)));
  }

  return {card};
})();
