/* Ручное выравнивание: четыре угла работы на фотографии (DEC-010, REQ-013).
   Углы хранятся долями размера снимка (0..1), порядок: верхний левый, верхний правый, нижний правый, нижний левый.
   Точку можно поставить щелчком, перетащить мышью или пальцем, сдвинуть стрелками на 1 %. */
'use strict';
const Corners = (() => {
  const {h, btn} = App;
  const NAMES = ['верхний левый', 'верхний правый', 'нижний правый', 'нижний левый'];

  function create(src, initial, onChange, instruction, options = {}) {
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
      NAMES.map((name, i) => btn(`${i + 1}. ${name}`, () => { selected = i; draw(); })));
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
          'aria-label': `Угол ${i + 1}: ${NAMES[i]}, ${(p[0] * 100).toFixed(0)} %, ${(p[1] * 100).toFixed(0)} %. Стрелки сдвигают на 1 %`});
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
      status.textContent = pts.length < 4 ? `Поставьте угол ${pts.length + 1} из 4: ${NAMES[pts.length]}.`
        : options.requireAllMoved && touched.size < 4 ? `Передвиньте все четыре угла на границы работы: уточнено ${touched.size} из 4.`
          : options.requireAnyMoved && touched.size === 0 ? 'Передвиньте хотя бы один неверный угол работы.'
          : 'Четыре угла поставлены. Можно применить выравнивание.';
    }
    function update(redraw) {
      const dots = wrap.querySelectorAll('.dot');
      pts.forEach((p, i) => { if (dots[i]) { dots[i].style.left = p[0] * 100 + '%'; dots[i].style.top = p[1] * 100 + '%'; } });
      if (redraw) draw();
      status.textContent = pts.length < 4 ? `Поставьте угол ${pts.length + 1} из 4: ${NAMES[pts.length]}.`
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
      chooser, status, h('div', {class: 'row'}, brightness, reset)), get: () => (pts.length === 4 ? pts.map((p) => [p[0], p[1]]) : null)};
  }
  return {create};
})();
