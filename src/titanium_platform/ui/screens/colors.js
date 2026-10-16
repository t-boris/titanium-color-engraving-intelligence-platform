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
      c.setAttribute('r', 6 + Math.min(8, (s.engravings || 1) * 2));
      c.setAttribute('fill', swatch(s.lab).style.background || '#888');
      c.setAttribute('stroke', s.available ? '#fff' : '#777');
      if (!s.available) c.setAttribute('stroke-dasharray', '3 2');
      const t = document.createElementNS(SVG, 'title');
      t.textContent = `${s.name ? s.name + ' · ' : ''}${labText(s.lab)} · гравировок ${s.engravings || 1}`;
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

  function variantSettings(p) {
    const source = p.source_settings || {};
    const wobble = source.wobbleEnable?.Value;
    return [
      params(p),
      `Q-Pulse ${p.pulse_width == null ? 'не записан' : p.pulse_width + ' нс'}`,
      p.line_interval == null ? null : `шаг ${p.line_interval} мм`,
      `${p.passes ?? '—'} проход(а)`,
      p.global_passes == null ? null : `глобально ${p.global_passes}×`,
      p.bidirectional == null ? null : `двунаправленно ${p.bidirectional ? 'да' : 'нет'}`,
      p.cross_hatch == null ? null : `перекрёстная заливка ${p.cross_hatch ? 'да' : 'нет'}`,
      p.scan_angle == null ? null : `угол ${p.scan_angle}°`,
      p.angle_increment == null ? null : `приращение угла ${p.angle_increment}°`,
      wobble == null ? null : wobble === '1'
        ? `Wobble: размер ${source.wobbleSize?.Value ?? '—'} мм, шаг ${source.wobbleStep?.Value ?? '—'} мм`
        : 'Wobble выключен',
    ].filter(Boolean).join(' · ');
  }

  function relativeCard(set) {
    const samples = set.samples || [];
    const variants = set.color_variants || [];
    const plotSamples = samples.map((s) => ({...s, engravings: 1, available: false}));
    const findingRows = (set.findings || []).map((f) => [f.label, f.name,
      h('span', {}, swatch(f.lab), labText(f.lab)), params(f.parameters), f.delta_e == null ? '—' : num(f.delta_e)]);
    const sampleRows = samples.flatMap((s) => {
      const main = [h('span', {}, swatch(s.lab), `${s.relative_appearance} · ${labText(s.lab)}`), s.name,
        h('div', {}, s.role === 'pre-test cleaning witness' ? 'Свидетель чистки' : s.role === 'registration, QR and engraved labels' ? 'Метки и подписи' : 'Тестовый участок',
          ...(s.notes || []).map((note) => h('div', {class: 'muted small'}, I18N.tr(note)))),
        params(s.parameters), num(s.delta_e_from_clean_witness), s.pixels == null ? '—' : num(s.pixels, 0)];
      const subs = (s.submeasurements || []).filter((sub) => sub.measured_lab).map((sub) => [
        h('span', {}, swatch(sub.measured_lab), labText(sub.measured_lab)), `${s.name} / ${sub.name}`, 'Часть слоя',
        params(s.parameters), num(sub.delta_e_from_clean_witness), sub.pixels == null ? '—' : num(sub.pixels, 0)]);
      return [main, ...subs];
    });
    const material = [set.material?.name, set.material?.grade, set.material?.batch && `партия ${set.material.batch}`].filter(Boolean).join(' · ');
    const variantCards = variants.map((v) => h('article', {class: 'color-variant'},
      h('div', {class: 'color-variant-head'}, swatch(v.lab), h('div', {}, h('strong', {}, v.name),
        h('span', {class: 'muted small'}, labText(v.lab)))),
      h('p', {class: 'small'}, variantSettings(v.parameters)),
      h('p', {class: 'muted small'}, `Отличие от очищенного фона на этом снимке: ΔE ${num(v.delta_e_from_clean_witness, 1)}`,
        v.settings_complete ? '' : ' · настройки неполные'),
      link('/analysis/' + set.pair_id, 'Фото и измерения')));
    return h('div', {class: 'card stack'},
      h('div', {class: 'row'}, h('div', {}, h('h3', {}, `${set.provisional ? 'Предварительные RAW-наблюдения' : 'RAW-наблюдения'} · пара ${set.pair_id}`),
        h('p', {class: 'muted small'}, `${set.photo_name || 'фото'} · ${set.lightburn_name || 'LightBurn'}${material ? ` · ${material}` : ''}`))),
      set.provisional ? h('div', {class: 'alert warn'}, `Результаты уже измерены, но ещё не приняты: ${set.masks_reviewed ? 'маски проверены' : 'нужно проверить наложение масок'}; состояние пары — ${set.status}. Это предварительные данные.`) : null,
      ...(set.warnings || []).map((warning) => h('div', {class: 'alert warn', role: 'status'}, I18N.tr(warning))),
      h('div', {class: 'alert warn'}, 'Это оттенки и Lab, измеренные относительно данного RAW-снимка. Карта показывает их для сравнения; они не участвуют в стандартных цветовых прогнозах и не сравниваются между разными фотосессиями.'),
      variants.length ? h('section', {}, h('h4', {}, `Цветовые варианты из тестовых квадратов · ${variants.length}`),
        h('p', {class: 'muted small'}, 'Каждый вариант связан с конкретным участком, настройками LightBurn и этим фото. Цвет плашки на экране условный; для рабочего рецепта нужен повтор с эталонной картой.'),
        h('div', {class: 'color-variant-grid'}, ...variantCards)) : null,
      h('h4', {}, 'Относительная карта a* × b*'), mapPlot(plotSamples),
      findingRows.length ? h('div', {}, h('h4', {}, 'Что видно в этой паре'),
        table(['Наблюдение', 'Слой', 'Оттенок на снимке', 'Параметры', 'ΔE от чистой поверхности'], findingRows)) : null,
      h('details', {}, h('summary', {}, `Все измеренные слои (${samples.length})`),
        table(['Оттенок на снимке', 'Слой', 'Роль', 'Параметры', 'ΔE от чистой поверхности', 'Пиксели'], sampleRows)),
      set.provisional ? link('/ingest?pair=' + set.pair_id, 'Открыть проверку слоёв и принять пару') : null);
  }

  App.register({id: 'colors', async render(ctx) {
    if (ctx.id === 'knowledge') return KnowledgeView.render(ctx.arg);
    if (!ctx.query.profile && !ctx.query.profileId) return ColorMap.render(ctx);     // the general map; ?profile= opens the model of one profile version
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
      h('span', {class: 'spacer'}));
    const controls = h('div', {class: 'toolbar'}, h('div', {class: 'f-wrap wide'}, field('Версия профиля', picker)), btn('Целевой цвет', () => predictDialog(pid), 'primary'), link('/designer?profile=' + pid, 'Спланировать эксперимент'));
    const relativeSets = map.camera_relative_sets || [];
    if (!map.samples.length && !relativeSets.length) return h('div', {class: 'stack'}, header, controls, h('div', {class: 'card empty'}, h('h3', {}, 'Для этой версии профиля пока нет проверенных измерений'), link('/ingest', 'Добавить фото эксперимента')));
    return h('div', {class: 'stack'}, header, controls,
      map.samples.length ? h('div', {class: 'card'}, h('h3', {}, 'Калиброванные наблюдения для прогноза'), mapPlot(map.samples),
        h('p', {class: 'muted small'}, 'Пунктир — наборы без оценок повторяемости. Цвета показаны как экранное представление Lab.')) : null,
      relativeSets.map(relativeCard),
      map.unstable.length ? h('div', {class: 'alert warn'}, 'Нестабильные наборы: ' + map.unstable.map((u) => `${u.parameters.power}/${u.parameters.frequency}/${u.parameters.speed}`).join(', ')) : null,
      rows.length ? h('div', {class: 'card'}, h('h3', {}, 'Модель цветовых параметров'), table(['Цвет', 'Мощность / частота / скорость', 'Стадия', 'Флаг', 'Независимых', 'Уверенность', 'Ошибка ΔE', 'Стабильность'], rows)) : null);
  }});
})();
