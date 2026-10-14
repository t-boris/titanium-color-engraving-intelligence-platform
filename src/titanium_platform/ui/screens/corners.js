/* Ручное выравнивание: четыре угла работы на фотографии (DEC-010, REQ-013).
   Углы хранятся долями размера снимка (0..1), порядок: верхний левый, верхний правый, нижний правый, нижний левый.
   Точку можно поставить щелчком, перетащить мышью или пальцем, сдвинуть стрелками на 1 %. */
'use strict';
const Corners = (() => {
  const {h, btn} = App;
  const NAMES = ['верхний левый', 'верхний правый', 'нижний правый', 'нижний левый'];

  function create(src, initial, onChange) {
    let pts = (initial || []).map((p) => [p[0], p[1]]);
    let selected = pts.length < 4 ? pts.length : 0;
    const img = h('img', {src, alt: 'Фотография работы: щёлкните, чтобы поставить угол', draggable: 'false'});
    const wrap = h('div', {class: 'photo'}, img);
    const status = h('p', {class: 'muted small', 'aria-live': 'polite'});
    const fraction = (ev) => {
      const r = img.getBoundingClientRect();
      return [Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)), Math.min(1, Math.max(0, (ev.clientY - r.top) / r.height))];
    };
    function draw() {
      wrap.querySelectorAll('.dot').forEach((d) => d.remove());
      pts.forEach((p, i) => {
        const dot = h('button', {type: 'button', class: 'dot', style: `left:${p[0] * 100}%;top:${p[1] * 100}%${i === selected ? ';outline:3px solid #fff' : ''}`,
          'aria-label': `Угол ${i + 1}: ${NAMES[i]}, ${(p[0] * 100).toFixed(0)} %, ${(p[1] * 100).toFixed(0)} %. Стрелки сдвигают на 1 %`});
        dot.append(String(i + 1));
        dot.addEventListener('pointerdown', (ev) => {
          selected = i; ev.preventDefault(); dot.setPointerCapture(ev.pointerId);
          const move = (e) => { pts[i] = fraction(e); update(false); };
          const up = () => { dot.removeEventListener('pointermove', move); dot.removeEventListener('pointerup', up); draw(); };
          dot.addEventListener('pointermove', move); dot.addEventListener('pointerup', up);
        });
        dot.addEventListener('keydown', (ev) => {
          const d = {ArrowLeft: [-0.01, 0], ArrowRight: [0.01, 0], ArrowUp: [0, -0.01], ArrowDown: [0, 0.01]}[ev.key];
          if (!d) return;
          ev.preventDefault();
          pts[i] = [Math.min(1, Math.max(0, p[0] + d[0])), Math.min(1, Math.max(0, p[1] + d[1]))];
          update(true); wrap.querySelectorAll('.dot')[i].focus();
        });
        wrap.append(dot);
      });
      status.textContent = pts.length < 4 ? `Поставьте угол ${pts.length + 1} из 4: ${NAMES[pts.length]}.` : 'Четыре угла поставлены. Нажмите «Применить выравнивание».';
    }
    function update(redraw) {
      const dots = wrap.querySelectorAll('.dot');
      pts.forEach((p, i) => { if (dots[i]) { dots[i].style.left = p[0] * 100 + '%'; dots[i].style.top = p[1] * 100 + '%'; } });
      if (redraw) draw();
      onChange(pts.length === 4 ? pts.map((p) => [p[0], p[1]]) : null);
    }
    img.addEventListener('click', (ev) => {
      if (pts.length < 4) { pts.push(fraction(ev)); selected = pts.length; } else { pts[selected % 4] = fraction(ev); }
      draw(); onChange(pts.length === 4 ? pts.map((p) => [p[0], p[1]]) : null);
    });
    const reset = btn('Сбросить углы', () => { pts = []; selected = 0; draw(); onChange(null); });
    draw();
    return {el: h('div', {class: 'stack'}, wrap, status, h('div', {class: 'row'}, reset)), get: () => (pts.length === 4 ? pts.map((p) => [p[0], p[1]]) : null)};
  }
  return {create};
})();
