/* Карта цветов и подбор параметров (REQ-002); маршрут /knowledge/:id открывает знание о цвете (knowledge.js). */
'use strict';
(() => {
  const {h, btn, field, link, pill, get, post, modal, table, num, labText, swatch, facts} = App;
  const {STAGE, stab, params} = KnowledgeView;
  const SVG = 'http://www.w3.org/2000/svg';

  function mapPlot(samples) {
    if (!samples.length) return h('p', {class: 'muted'}, 'Нет измеренных цветов');
    const W = 520, H = 360, a = samples.map((s) => s.lab[1]), b = samples.map((s) => s.lab[2]);
    const lo = [Math.min(...a) - 8, Math.min(...b) - 8], hi = [Math.max(...a) + 8, Math.max(...b) + 8];
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Карта измеренных цветов в плоскости a и b');
    svg.style.cssText = 'width:100%;max-width:720px';   // look comes from styles.css (svg[role=img])
    samples.forEach((s) => {
      const c = document.createElementNS(SVG, 'circle');
      c.setAttribute('cx', 20 + ((s.lab[1] - lo[0]) / (hi[0] - lo[0])) * (W - 40));
      c.setAttribute('cy', H - 20 - ((s.lab[2] - lo[1]) / (hi[1] - lo[1])) * (H - 40));
      c.setAttribute('r', 6 + Math.min(8, s.engravings * 2));
      c.setAttribute('fill', swatch(s.lab).style.background || '#888');
      c.setAttribute('stroke', s.available ? '#fff' : '#777');
      if (!s.available) c.setAttribute('stroke-dasharray', '3 2');
      const t = document.createElementNS(SVG, 'title');
      t.textContent = `${labText(s.lab)} · гравировок ${s.engravings}`;
      c.append(t);
      svg.append(c);
    });
    return svg;
  }

  function predictDialog(pid) {
    const L = h('input', {type: 'number', step: 'any', value: 50}), a = h('input', {type: 'number', step: 'any', value: 0}), b = h('input', {type: 'number', step: 'any', value: 0});
    const out = h('div', {class: 'stack'});
    modal('Целевой цвет', h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, field('L (0–100)', L), field('a (−128…127)', a), field('b (−128…127)', b)), out), [
      {label: 'Закрыть', run: (m) => m.close()},
      {label: 'Подобрать параметры', cls: 'primary', run: async () => {
        const r = await post(`/profiles/${pid}/predict`, {lab: [+L.value, +a.value, +b.value]});
        out.replaceChildren(!r.available
          ? h('div', {class: 'alert warn'}, 'Недостаточно данных для прогноза: параметры без уверенности, ошибки и стабильности не выдаются.')
          : h('div', {class: 'stack'}, r.outside_coverage ? h('div', {class: 'alert warn'}, 'Вне измеренного цветового пространства') : h('div', {class: 'alert ok'}, 'В пределах измеренного покрытия'),
            facts([['Прогнозный цвет', h('span', {}, swatch(r.lab), labText(r.lab))], ['Расстояние ΔE до цели', num(r.distance_to_target)], ['Параметры', params(r.parameters)],
              ['Уверенность', num(r.confidence)], ['Ожидаемая ошибка ΔE', num(r.expected_delta_e)], ['Стабильность', stab(r.stability)]])));
      }}]);
  }

  App.register({id: 'colors', async render(ctx) {
    if (ctx.id === 'knowledge') return KnowledgeView.render(ctx.arg);
    const profiles = await get('/profiles');
    if (!profiles.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Нет измеренных цветов'), link('/profiles', 'Профили'), ' ', link('/ingest', 'Добавить наблюдение'));
    const pid = +(ctx.query.profile || ctx.query.profileId || profiles[profiles.length - 1].id);
    const [map, know] = await Promise.all([get(`/profiles/${pid}/map`), get(`/profiles/${pid}/knowledge`)]);
    const picker = h('select', {'aria-label': 'Версия профиля', onChange: (e) => { location.hash = '#/colors?profile=' + e.target.value; }},
      profiles.map((p) => h('option', {value: p.id, selected: p.id === pid}, `${p.name} · версия ${p.version}`)));
    const rows = know.map((k) => {
      const s = k.summary;
      return [link('/knowledge/' + k.id, labText(s && s.lab)), `${num(k.parameters.power, 1)} / ${num(k.parameters.frequency, 0)} / ${num(k.parameters.speed, 0)}`,
        pill(STAGE[k.stage], k.stage === 'production' ? 'ok' : ''), k.questioned ? pill('под вопросом', 'bad') : '', s ? s.independent_engravings : 0,
        s && s.available ? num(s.confidence) : '—', s && s.available ? num(s.expected_delta_e) : '—', s ? stab(s.stability) : '—'];
    });
    const header = h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Карта цветов и подбор параметров'), h('p', {class: 'sub'}, 'Данные разных версий профиля не объединяются.')),
      h('span', {class: 'spacer'}), h('div', {style: 'min-width:240px'}, field('Версия профиля', picker)), btn('Целевой цвет', () => predictDialog(pid), 'primary'), link('/designer?profile=' + pid, 'Спланировать эксперимент'));
    if (!map.samples.length) return h('div', {class: 'stack'}, header, h('div', {class: 'card empty'}, h('h3', {}, 'Для этой версии профиля нет наблюдений'), link('/ingest', 'Добавить наблюдение')));
    return h('div', {class: 'stack'}, header,
      h('div', {class: 'card'}, h('h3', {}, 'Покрытие в плоскости a × b'), mapPlot(map.samples),
        h('p', {class: 'muted small'}, 'Пунктир — наборы без оценок (одна гравировка). Карта — приблизительное экранное представление Lab.')),
      map.unstable.length ? h('div', {class: 'alert warn'}, 'Нестабильные наборы: ' + map.unstable.map((u) => `${u.parameters.power}/${u.parameters.frequency}/${u.parameters.speed}`).join(', ')) : null,
      h('div', {class: 'card'}, h('h3', {}, 'Знание'), table(['Цвет', 'Мощность / частота / скорость', 'Стадия', 'Флаг', 'Независимых', 'Уверенность', 'Ошибка ΔE', 'Стабильность'], rows)));
  }});
})();
