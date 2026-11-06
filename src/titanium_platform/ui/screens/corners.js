/* Manual photo alignment: four corners stored as image fractions. Points support click, drag, arrow keys and numeric entry (DEC-010, REQ-013). */
'use strict';
const Corners = (() => {
  const {h, btn} = App;
  const NAMES = ['top left', 'top right', 'bottom right', 'bottom left'];

  /** ``options.names``: four other names for the points, when their order is not the photograph's (the corners of a detail of the file). */
  function create(src, initial, onChange, instruction, options = {}) {
    const names = Array.isArray(options.names) && options.names.length === 4 ? options.names : NAMES;
    let pts = (initial || []).map((p) => [p[0], p[1]]);
    let selected = pts.length < 4 ? pts.length : 0;
    const touched = new Set();
    let lifted = true;
    const imageUrl = () => `${src}${src.includes('?') ? '&' : '?'}visibility=${lifted ? 'lifted' : 'normal'}`;
    const img = h('img', {src: imageUrl(), alt: 'Work photograph: click to place a corner', draggable: 'false'});
    const brightness = btn('Normal brightness', () => {
      lifted = !lifted; img.src = imageUrl();
      brightness.textContent = lifted ? 'Normal brightness' : 'Increase brightness';
    });
    const wrap = h('div', {class: 'photo'}, img);
    const status = h('p', {class: 'muted small', 'aria-live': 'polite'});
    const chooser = h('div', {class: 'row corner-chooser', role: 'group', 'aria-label': 'Choose the corner for the next photo click'},
      names.map((name, i) => btn(`${i + 1}. ${name}`, () => { selected = i; draw(); })));
    // the corners by numbers: a person who cannot aim at the picture still places, moves and checks every corner
    const nums = names.map((name, i) => ['x', 'y'].map((axis) => h('input', {type: 'number', min: '0', max: '100', step: '0.1', class: 'corner-num',
      'aria-label': `Corner ${i + 1}: ${axis === 'x' ? 'from left' : 'from top'}, %`})));
    const numRules = nums.map((pair) => pair.map((input) => Forms.describe(input, 'cornerShare')));        // unit: %, allowed: 0 to 100
    const numNote = h('p', {class: 'small', role: 'status', 'aria-live': 'polite'});
    const numbers = h('div', {class: 'corner-nums', role: 'group', 'aria-label': 'Corner coordinates as percentages of image width and height'},
      names.map((name, i) => h('div', {class: 'corner-num-row', role: 'group', 'aria-label': `Corner ${i + 1}: ${name}`},
        h('strong', {class: 'corner-num-name'}, `${i + 1}. ${name}`),
        h('label', {class: 'f'}, h('span', {}, 'from left, %'), nums[i][0], numRules[i][0]), h('label', {class: 'f'}, h('span', {}, 'from top, %'), nums[i][1], numRules[i][1]))));
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
        numNote.textContent = `Corner ${i + 1}: enter both coordinates, from left and top`;
        return;
      }
      const bad = incomplete ? `Corner ${i + 1}: both coordinates are required`
        : x < 0 || x > 100 || y < 0 || y > 100 ? `Corner ${i + 1}: values must be from 0 to 100%` : null;
      numNote.setAttribute('class', bad ? 'small alert bad' : 'small');
      if (bad) { numNote.textContent = bad; syncNumbers(); return; }       // the corner stays where it was, the fields say so
      if (i === pts.length) pts.push([x / 100, y / 100]); else pts[i] = [x / 100, y / 100];
      selected = i; touched.add(i);
      numNote.textContent = `Corner ${i + 1} (${names[i]}): ${pct(x / 100)} % from left, ${pct(y / 100)} % from top`;
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
          'aria-label': `Corner ${i + 1}: ${names[i]}, ${(p[0] * 100).toFixed(0)} %, ${(p[1] * 100).toFixed(0)} %. Arrow keys move it by 1%`});
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
      status.textContent = pts.length < 4 ? `Place corner ${pts.length + 1} of 4: ${names[pts.length]}.`
        : options.requireAllMoved && touched.size < 4 ? `Move all four corners to the work boundaries: ${touched.size} of 4 adjusted.`
          : options.requireAnyMoved && touched.size === 0 ? 'Move at least one incorrect corner.'
          : 'Four corners are placed. Alignment can be applied.';
      syncNumbers();
    }
    function update(redraw) {
      const dots = wrap.querySelectorAll('.dot');
      pts.forEach((p, i) => { if (dots[i]) { dots[i].style.left = p[0] * 100 + '%'; dots[i].style.top = p[1] * 100 + '%'; } });
      syncNumbers();
      if (redraw) draw();
      status.textContent = pts.length < 4 ? `Place corner ${pts.length + 1} of 4: ${names[pts.length]}.`
        : options.requireAllMoved && touched.size < 4 ? `Move all four corners to the work boundaries: ${touched.size} of 4 adjusted.`
          : options.requireAnyMoved && touched.size === 0 ? 'Move at least one incorrect corner.'
          : 'Four corners are placed. Alignment can be applied.';
      onChange(pts.length === 4 && (!options.requireAllMoved || touched.size === 4) &&
        (!options.requireAnyMoved || touched.size > 0) ? pts.map((p) => [p[0], p[1]]) : null);
    }
    img.addEventListener('click', (ev) => {
      if (pts.length < 4) { pts.push(fraction(ev)); selected = pts.length - 1; touched.add(selected); }
      else { pts[selected % 4] = fraction(ev); touched.add(selected % 4); }
      draw(); update(false);
    });
    const reset = btn('Reset corners', () => { pts = []; touched.clear(); selected = 0; draw(); onChange(null); });
    draw();
    return {el: h('div', {class: 'stack'}, wrap,
      h('p', {class: 'muted small'}, instruction || 'Mark corners clockwise: top left → top right → bottom right → bottom left. Numbers are offset inward; the small dot shows the exact position.'),
      chooser, status, numbers, numNote, h('div', {class: 'row'}, brightness, reset)), get: () => (pts.length === 4 ? pts.map((p) => [p[0], p[1]]) : null)};
  }
  return {create};
})();
