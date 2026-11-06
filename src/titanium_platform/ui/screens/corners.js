/* Ручное выравнивание: четыре угла работы на фотографии (DEC-010, REQ-013).
   Углы хранятся долями размера снимка (0..1), порядок: верхний левый, верхний правый, нижний правый, нижний левый.
   Точку можно поставить щелчком, перетащить мышью или пальцем, сдвинуть стрелками на 1 % или задать числами (ux-accessible-layout-p0):
   у каждого угла два поля, процент ширины и высоты снимка; ставятся по порядку, как щелчками. */
'use strict';
const Corners = (() => {
  const {h, btn} = App;
  const NAMES = ['верхний левый', 'верхний правый', 'нижний правый', 'нижний левый'];

  /** ``options.names``: four other names for the points, when their order is not the photograph's (the corners of a detail of the file). */
  function create(src, initial, onChange, instruction, options = {}) {
    const names = Array.isArray(options.names) && options.names.length === 4 ? options.names : NAMES;
    let pts = (initial || []).map((p) => [p[0], p[1]]);
    let selected = pts.length < 4 ? pts.length : 0;
    const touched = new Set();
    let lifted = true;
    const imageUrl = () => `${src}${src.includes('?') ? '&' : '?'}visibility=${lifted ? 'lifted' : 'normal'}`;
    const img = h('img', {src: imageUrl(), alt: 'Фотография работы: щёлкните, чтобы поставить угол', draggable: 'false'});
    const brightness = btn('Обычная яркость', () => {
      lifted = !lifted; img.src = imageUrl();
      brightness.textContent = lifted ? 'Обычная яркость' : 'Повысить яркость';
    });
    const wrap = h('div', {class: 'photo'}, img);
    const status = h('p', {class: 'muted small', 'aria-live': 'polite'});
    const chooser = h('div', {class: 'row corner-chooser', role: 'group', 'aria-label': 'Выберите угол для следующего щелчка по фото'},
      names.map((name, i) => btn(`${i + 1}. ${name}`, () => { selected = i; draw(); })));
    // the corners by numbers: a person who cannot aim at the picture still places, moves and checks every corner
    const nums = names.map((name, i) => ['x', 'y'].map((axis) => h('input', {type: 'number', min: '0', max: '100', step: '0.1', class: 'corner-num',
      'aria-label': `Угол ${i + 1}: ${axis === 'x' ? 'слева' : 'сверху'}, %`})));
    const numRules = nums.map((pair) => pair.map((input) => Forms.describe(input, 'cornerShare')));        // «единица: %, допустимо: от 0 до 100»
    const numNote = h('p', {class: 'small', role: 'status', 'aria-live': 'polite'});
    const numbers = h('div', {class: 'corner-nums', role: 'group', 'aria-label': 'Углы числами, в процентах ширины и высоты снимка'},
      names.map((name, i) => h('div', {class: 'corner-num-row', role: 'group', 'aria-label': `Угол ${i + 1}: ${name}`},
        h('strong', {class: 'corner-num-name'}, `${i + 1}. ${name}`),
        h('label', {class: 'f'}, h('span', {}, 'слева, %'), nums[i][0], numRules[i][0]), h('label', {class: 'f'}, h('span', {}, 'сверху, %'), nums[i][1], numRules[i][1]))));
    const pct = (v) => String(Math.round(v * 1000) / 10);
    function syncNumbers() {
      nums.forEach(([x, y], i) => {
        x.value = pts[i] ? pct(pts[i][0]) : ''; y.value = pts[i] ? pct(pts[i][1]) : '';
        x.disabled = y.disabled = i > pts.length;                       // the next corner is the one to place, after the ones before it
      });
    }
    function placeByNumbers(i) {
      if (i > pts.length) return;
      const x = parseFloat(nums[i][0].value), y = parseFloat(nums[i][1].value);
      const incomplete = !Number.isFinite(x) || !Number.isFinite(y);
      if (incomplete && i >= pts.length) {                              // a corner not placed yet: the other number is still to come
        numNote.setAttribute('class', 'small');
        numNote.textContent = `Угол ${i + 1}: укажите оба числа — слева и сверху`;
        return;
      }
      const bad = incomplete ? `Угол ${i + 1}: нужны оба числа — слева и сверху`
        : x < 0 || x > 100 || y < 0 || y > 100 ? `Угол ${i + 1}: числа — от 0 до 100 %` : null;
      numNote.setAttribute('class', bad ? 'small alert bad' : 'small');
      if (bad) { numNote.textContent = bad; syncNumbers(); return; }       // the corner stays where it was, the fields say so
      if (i === pts.length) pts.push([x / 100, y / 100]); else pts[i] = [x / 100, y / 100];
      selected = i; touched.add(i);
      numNote.textContent = `Угол ${i + 1} (${names[i]}): ${pct(x / 100)} % слева, ${pct(y / 100)} % сверху`;
      draw(); update(false);
    }
    nums.forEach((pair, i) => pair.forEach((input) => input.addEventListener('change', () => placeByNumbers(i))));
    const fraction = (ev) => {
      // Dots are positioned against .photo, so use that same box for pointer
      // coordinates too; the image and overlay then share one frame on resize.
      // The box is the photograph's only because .photo is as wide as its picture (width: fit-content in styles.css).
      const r = wrap.getBoundingClientRect();
      return [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))];
    };
    function draw() {
      wrap.querySelectorAll('.dot').forEach((d) => d.remove());
      [...chooser.children].forEach((button, i) => button.setAttribute('aria-pressed', String(i === selected)));
      pts.forEach((p, i) => {
        const dot = h('button', {type: 'button', class: `dot corner-${i + 1}`, style: `left:${p[0] * 100}%;top:${p[1] * 100}%${i === selected ? ';outline:3px solid #fff' : ''}`,
          'aria-label': `Угол ${i + 1}: ${names[i]}, ${(p[0] * 100).toFixed(0)} %, ${(p[1] * 100).toFixed(0)} %. Стрелки сдвигают на 1 %`});
        dot.append(h('span', {class: 'dot-label', 'aria-hidden': 'true'}, String(i + 1)));
        dot.addEventListener('pointerdown', (ev) => {
          selected = i; ev.preventDefault(); dot.setPointerCapture(ev.pointerId);
          const move = (e) => { pts[i] = fraction(e); touched.add(i); update(false); };
          const up = () => { dot.removeEventListener('pointermove', move); dot.removeEventListener('pointerup', up); draw(); };
          dot.addEventListener('pointermove', move); dot.addEventListener('pointerup', up);
        });
        dot.addEventListener('keydown', (ev) => {
          const d = {ArrowLeft: [-0.01, 0], ArrowRight: [0.01, 0], ArrowUp: [0, -0.01], ArrowDown: [0, 0.01]}[ev.key];
          if (!d) return;
          ev.preventDefault();
          pts[i] = [Math.min(1, Math.max(0, p[0] + d[0])), Math.min(1, Math.max(0, p[1] + d[1]))];
          touched.add(i);
          update(true); wrap.querySelectorAll('.dot')[i].focus();
        });
        wrap.append(dot);
      });
      status.textContent = pts.length < 4 ? `Поставьте угол ${pts.length + 1} из 4: ${names[pts.length]}.`
        : options.requireAllMoved && touched.size < 4 ? `Передвиньте все четыре угла на границы работы: уточнено ${touched.size} из 4.`
          : options.requireAnyMoved && touched.size === 0 ? 'Передвиньте хотя бы один неверный угол работы.'
          : 'Четыре угла поставлены. Можно применить выравнивание.';
      syncNumbers();
    }
    function update(redraw) {
      const dots = wrap.querySelectorAll('.dot');
      pts.forEach((p, i) => { if (dots[i]) { dots[i].style.left = p[0] * 100 + '%'; dots[i].style.top = p[1] * 100 + '%'; } });
      syncNumbers();
      if (redraw) draw();
      status.textContent = pts.length < 4 ? `Поставьте угол ${pts.length + 1} из 4: ${names[pts.length]}.`
        : options.requireAllMoved && touched.size < 4 ? `Передвиньте все четыре угла на границы работы: уточнено ${touched.size} из 4.`
          : options.requireAnyMoved && touched.size === 0 ? 'Передвиньте хотя бы один неверный угол работы.'
          : 'Четыре угла поставлены. Можно применить выравнивание.';
      onChange(pts.length === 4 && (!options.requireAllMoved || touched.size === 4) &&
        (!options.requireAnyMoved || touched.size > 0) ? pts.map((p) => [p[0], p[1]]) : null);
    }
    img.addEventListener('click', (ev) => {
      if (pts.length < 4) { pts.push(fraction(ev)); selected = pts.length - 1; touched.add(selected); }
      else { pts[selected % 4] = fraction(ev); touched.add(selected % 4); }
      draw(); update(false);
    });
    const reset = btn('Сбросить углы', () => { pts = []; touched.clear(); selected = 0; draw(); onChange(null); });
    draw();
    return {el: h('div', {class: 'stack'}, wrap,
      h('p', {class: 'muted small'}, instruction || 'Отмечайте углы по часовой стрелке: верхний левый → верхний правый → нижний правый → нижний левый. Цифры сдвинуты внутрь кадра; маленькая точка показывает точную позицию.'),
      chooser, status, numbers, numNote, h('div', {class: 'row'}, brightness, reset)), get: () => (pts.length === 4 ? pts.map((p) => [p[0], p[1]]) : null)};
  }
  return {create};
})();
