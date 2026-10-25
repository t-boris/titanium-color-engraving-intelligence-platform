/* Карта цветов одного лазера с линзой и подбор параметров (REQ-002, REQ-044, DEC-080); маршрут /knowledge/:id открывает знание о цвете (knowledge.js).
   Страница на один экран: слева наборы (калиброванные наблюдения и RAW-пары), посередине карта выбранного набора с оговорками,
   справа его таблицы во вкладках; прокручиваются только длинные списки внутри своих панелей. Выбранные набор и вкладку браузер помнит
   (удобство одного зрителя: без хранилища экран открывается на первом наборе).
   The model of colour parameters and the RAW «Все слои» are short lists (findings-you-can-manage-short-lists-re-check, REQ-005,
   DEC-090): one line per entry or layer, its figures under the line on a click, a search, filters, a sort and pages of 20. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, post, modal, num, labText, swatch, facts} = App;
  const {STAGE, stab, params} = KnowledgeView;
  const STAGES = Object.keys(STAGE);                       // measured … production: the order in which an entry earns trust
  const SVG = 'http://www.w3.org/2000/svg';
  const PAIR_STATUS = {'Awaiting check': 'ожидает проверки', 'Needs correction': 'требует исправления', 'Ready to accept': 'готова к принятию',
    Accepted: 'принята'};
  // what a RAW layer was engraved for
  const ROLE = {test: 'Тестовый участок', witness: 'Свидетель чистки', labels: 'Метки и подписи'};
  const roleOf = (s) => (s.role === 'pre-test cleaning witness' ? 'witness' : s.role === 'registration, QR and engraved labels' ? 'labels' : 'test');

  const SET_KEY = 'lm.set', TAB_KEY = 'lm.tab';
  const stored = (key) => { try { return localStorage.getItem(key); } catch (_) { return null; } };
  const keep = (key, value) => { try { localStorage.setItem(key, value); } catch (_) { /* a viewer without storage starts on the first set */ } };

  /** ``fit`` draws a square map that fills its box (the one-screen page); otherwise the map keeps its fixed proportions. */
  function mapPlot(samples, {fit = false} = {}) {
    if (!samples.length) return h('p', {class: 'muted'}, 'Нет измеренных цветов');
    const W = 520, H = fit ? 520 : 360, a = samples.map((s) => s.lab[1]), b = samples.map((s) => s.lab[2]);
    const lo = [Math.min(...a) - 8, Math.min(...b) - 8], hi = [Math.max(...a) + 8, Math.max(...b) + 8];
    const svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Карта измеренных цветов в плоскости a и b');
    svg.style.cssText = fit ? 'width:100%;height:100%' : 'width:100%;max-width:720px';   // look comes from styles.css (svg[role=img])
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

  function predictDialog(pick) {
    const L = h('input', {type: 'number', step: 'any', value: 50}), a = h('input', {type: 'number', step: 'any', value: 0}), b = h('input', {type: 'number', step: 'any', value: 0});
    const out = h('div', {class: 'stack'});
    modal('Целевой цвет', h('div', {class: 'stack'}, h('div', {class: 'grid g3'}, field('L (0–100)', L), field('a (−128…127)', a), field('b (−128…127)', b)), out), [
      {label: 'Закрыть', run: (m) => m.close()},
      {label: 'Подобрать параметры', cls: 'primary', run: async () => {
        const r = await post('/predict', {device_id: pick.deviceId(), lens_id: pick.lensId(), lab: [+L.value, +a.value, +b.value]});
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

  /** One line of a compact list: the main part (swatch, name, pills) and, under it, the figures that used to be table columns. */
  const item = (top, sub, cls = '') => h('div', {class: 'lm-item ' + cls}, h('div', {class: 'lm-item-top'}, ...top),
    sub && sub.length ? h('div', {class: 'lm-item-sub'}, ...sub) : null);
  const dot = (parts) => parts.filter((x) => x != null && x !== '').join(' · ');

  /** What the page shows of one set of camera-relative (RAW) observations: its heading, the map, the cautions and the tabs. */
  function relativeView(set) {
    const samples = set.samples || [];
    const variants = set.color_variants || [];
    const plotSamples = samples.map((s) => ({...s, engravings: 1, available: false}));
    const findingRows = (set.findings || []).map((f) => item([swatch(f.lab), h('strong', {}, `${f.label} · ${f.name}`), h('span', {class: 'muted small'}, labText(f.lab))],
      [dot([params(f.parameters), `ΔE от чистой поверхности ${f.delta_e == null ? '—' : num(f.delta_e)}`])]));
    // every measured layer is one line of a short list; its figures, notes and measured parts open under the line
    const partsOf = (s) => (s.submeasurements || []).filter((sub) => sub.measured_lab);
    const part = (s, sub) => item([swatch(sub.measured_lab), h('strong', {}, `${s.name} / ${sub.name}`), h('span', {class: 'muted small'}, labText(sub.measured_lab))],
      [dot(['Часть слоя', params(s.parameters), `ΔE от чистой поверхности ${num(sub.delta_e_from_clean_witness)}`, `пикселей ${sub.pixels == null ? '—' : num(sub.pixels, 0)}`])], 'lm-sub');
    const contrast = (s) => s.delta_e_from_clean_witness ?? -1;            // the witness itself has none: last
    const layerList = () => App.list({id: 'lm.layers.' + set.pair_id, items: samples.map((s, at) => ({s, at})), key: (x) => x.at,
      search: ({s}) => `${s.name} ${s.relative_appearance || ''} ${ROLE[roleOf(s)]}`,
      row: ({s}) => [swatch(s.lab), h('span', {class: 'lst-text', title: dot([s.name, s.relative_appearance])}, dot([s.name, s.relative_appearance])),
        roleOf(s) === 'test' ? null : pill(ROLE[roleOf(s)]),
        s.delta_e_from_clean_witness == null ? null : h('span', {class: 'small'}, `ΔE ${num(s.delta_e_from_clean_witness, 1)}`),
        partsOf(s).length ? h('span', {class: 'muted small'}, `частей ${partsOf(s).length}`) : null],
      details: ({s}) => h('div', {class: 'stack small'},
        h('p', {}, dot([ROLE[roleOf(s)], labText(s.lab), params(s.parameters), `ΔE от чистой поверхности ${num(s.delta_e_from_clean_witness)}`,
          `пикселей ${s.pixels == null ? '—' : num(s.pixels, 0)}`])),
        ...(s.notes || []).map((note) => h('p', {class: 'muted'}, I18N.tr(note))),
        partsOf(s).length ? h('div', {class: 'lm-list'}, ...partsOf(s).map((sub) => part(s, sub))) : null),
      filters: [{key: 'role', label: 'Роль слоя', options: Object.entries(ROLE), test: ({s}, v) => roleOf(s) === v}],
      sorts: [['order', 'По порядку', (p, q) => p.at - q.at],
        ['contrast', 'Сильнее отличаются от чистой поверхности', (p, q) => contrast(q.s) - contrast(p.s) || p.at - q.at],
        ['light', 'Сначала светлые', (p, q) => q.s.lab[0] - p.s.lab[0] || p.at - q.at]],
      empty: 'Под выбранные условия слоёв нет.'}).el;
    const material = [set.material?.name, set.material?.grade, set.material?.batch && `партия ${set.material.batch}`].filter(Boolean).join(' · ');
    // every colour variant is one line of a short list too; its settings and the link to the photograph open under the line
    const variantList = () => App.list({id: 'lm.variants.' + set.pair_id, items: variants.map((v, at) => ({v, at})), key: (x) => x.at,
      search: ({v}) => `${v.name} ${variantSettings(v.parameters)}`,
      row: ({v}) => [swatch(v.lab), h('span', {class: 'lst-text', title: v.name}, v.name), h('span', {class: 'muted small'}, labText(v.lab)),
        h('span', {class: 'small'}, `ΔE ${num(v.delta_e_from_clean_witness, 1)}`), v.settings_complete ? null : pill('настройки неполные', 'warn')],
      details: ({v}) => h('div', {class: 'stack small'}, h('p', {}, variantSettings(v.parameters)),
        h('p', {class: 'muted'}, `Отличие от очищенного фона на этом снимке: ΔE ${num(v.delta_e_from_clean_witness, 1)}`, v.settings_complete ? '' : ' · настройки неполные'),
        link('/analysis/' + set.pair_id, 'Фото и измерения')),
      sorts: [['order', 'По порядку', (p, q) => p.at - q.at],
        ['contrast', 'Сильнее отличаются от чистой поверхности', (p, q) => (q.v.delta_e_from_clean_witness ?? -1) - (p.v.delta_e_from_clean_witness ?? -1) || p.at - q.at],
        ['light', 'Сначала светлые', (p, q) => q.v.lab[0] - p.v.lab[0] || p.at - q.at]],
      empty: 'Под выбранные условия вариантов нет.'}).el;
    const alerts = [
      set.provisional ? h('div', {class: 'alert warn'}, `Результаты уже измерены, но ещё не приняты: ${set.masks_reviewed ? 'маски проверены' : 'нужно проверить наложение масок'}; состояние пары — ${PAIR_STATUS[set.status] || set.status}. Это предварительные данные.`) : null,
      ...(set.warnings || []).map((warning) => h('div', {class: 'alert warn', role: 'status'}, I18N.tr(warning))),
      h('div', {class: 'alert warn'}, 'Это оттенки и Lab, измеренные относительно данного RAW-снимка. Карта показывает их для сравнения; они не участвуют в стандартных цветовых прогнозах и не сравниваются между разными фотосессиями.'),
      set.provisional ? link('/ingest?pair=' + set.pair_id, 'Открыть проверку слоёв и принять пару') : null];
    const list = (rows, empty) => (rows.length ? h('div', {class: 'lm-list'}, ...rows) : h('p', {class: 'muted'}, empty));
    return {
      title: `${set.provisional ? 'Предварительные RAW-наблюдения' : 'RAW-наблюдения'} · пара ${set.pair_id}`,
      sub: `${set.photo_name || 'фото'} · ${set.lightburn_name || 'LightBurn'}${material ? ` · ${material}` : ''}`,
      plot: mapPlot(plotSamples, {fit: true}), plotTitle: 'Относительная карта a* × b*', alerts,
      tabs: [['seen', `Что видно (${findingRows.length})`, h('div', {class: 'stack'}, h('h4', {}, 'Что видно в этой паре'), list(findingRows, 'Нет данных'))],
        ['variants', `Варианты (${variants.length})`, h('div', {class: 'stack'}, h('h4', {}, `Цветовые варианты из тестовых квадратов · ${variants.length}`),
          variants.length ? h('p', {class: 'muted small'}, 'Каждый вариант связан с конкретным участком, настройками LightBurn и этим фото. Цвет плашки на экране условный; для рабочего рецепта нужен повтор с эталонной картой.') : null,
          variants.length ? variantList() : h('p', {class: 'muted'}, 'Нет данных'))],
        ['layers', `Все слои (${samples.length})`, h('div', {class: 'stack'}, h('h4', {}, `Все измеренные слои (${samples.length})`),
          samples.length ? layerList() : h('p', {class: 'muted'}, 'Нет данных'))]]};
  }

  /** The calibrated observations the forecast is made from: the map of every sample and the model of colour parameters beside it.
      The model is a short list: one line per entry (its settings and colour, stage, doubt, expected error), the figures under the line
      on a click and «Открыть» to the entry's own page; the choices are kept under ``listId`` (one laser and lens). */
  function calibratedView(map, know, listId) {
    const rank = (k) => STAGES.indexOf(k.stage);
    const taskOf = (k) => (k.summary && k.summary.task && k.summary.task.kind) || '';
    const error = (k) => (k.summary && k.summary.available ? k.summary.expected_delta_e : Infinity);          // no estimate: last
    const engravings = (k) => (k.summary ? k.summary.independent_engravings : 0);
    const lightness = (k) => (k.summary ? k.summary.lab[0] : -1);
    const tasks = [...new Set(know.map(taskOf).filter(Boolean))];
    const model = () => App.list({id: listId, items: know, key: (k) => k.id,
      search: (k) => [params(k.parameters), labText(k.summary && k.summary.lab), STAGE[k.stage], taskOf(k) && Tasks.name(taskOf(k))].join(' '),
      row: (k) => {
        const s = k.summary, text = dot([params(k.parameters), s && labText(s.lab)]);
        return [s ? swatch(s.lab) : null, h('span', {class: 'lst-text', title: text}, text),
          pill(STAGE[k.stage] || k.stage, k.stage === 'production' ? 'ok' : ''), k.questioned ? pill('под вопросом', 'bad') : null,
          s && s.available ? h('span', {class: 'small'}, `ΔE ${num(s.expected_delta_e, 1)}`) : null];
      },
      details: (k) => {
        const s = k.summary;
        return h('div', {class: 'stack small'}, h('p', {}, variantSettings(k.parameters)),
          h('p', {}, dot([s && labText(s.lab), `независимых ${s ? s.independent_engravings : 0}`, `уверенность ${s && s.available ? num(s.confidence) : '—'}`,
            `ошибка ΔE ${s && s.available ? num(s.expected_delta_e) : '—'}`, `стабильность ${s ? stab(s.stability) : '—'}`])),
          taskOf(k) ? h('p', {class: 'muted'}, `Задача: ${Tasks.name(taskOf(k))}`) : null,
          k.questioned && k.doubt ? h('p', {}, h('strong', {}, 'Под вопросом. '), I18N.tr(k.doubt.reason)) : null);
      },
      actions: (k) => [h('a', {class: 'btn btn-small', href: '#/knowledge/' + k.id}, 'Открыть')],
      filters: [{key: 'stage', label: 'Стадия', options: Object.entries(STAGE), test: (k, v) => k.stage === v},
        {key: 'questioned', label: 'Под вопросом', select: true, options: [['yes', 'да'], ['no', 'нет']], test: (k, v) => k.questioned === (v === 'yes')},
        ...(tasks.length ? [{key: 'task', label: 'Задача', select: true, options: tasks.map((t) => [t, Tasks.name(t)]), test: (k, v) => taskOf(k) === v}] : [])],
      sorts: [['stage', 'По стадии', (p, q) => rank(q) - rank(p) || p.id - q.id],
        ['error', 'Меньшая ошибка ΔE', (p, q) => (error(p) === error(q) ? 0 : error(p) - error(q)) || p.id - q.id],
        ['engravings', 'Больше гравировок', (p, q) => engravings(q) - engravings(p) || p.id - q.id],
        ['light', 'Сначала светлые', (p, q) => lightness(q) - lightness(p) || p.id - q.id],
        ['newest', 'Сначала новые', (p, q) => q.id - p.id]],
      empty: 'Под выбранные условия записей нет.'}).el;
    return {title: 'Калиброванные наблюдения для прогноза', sub: `${map.samples.length} измеренных цветов`, plot: mapPlot(map.samples, {fit: true}), plotTitle: null,
      alerts: [h('p', {class: 'muted small'}, 'Пунктир — наборы без оценок повторяемости. Цвета показаны как экранное представление Lab.')],
      model: {count: know.length, body: know.length ? model() : h('p', {class: 'muted'}, 'Нет данных')}};
  }

  App.register({id: 'colors', async render(ctx) {
    if (ctx.id === 'knowledge') return KnowledgeView.render(ctx.arg);
    if (!ctx.query.device) return ColorMap.render(ctx);     // the general map; ?device=&lens= opens the model of one laser and lens
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Нет измеренных цветов'), link('/devices', 'Лазеры'), ' ', link('/ingest', 'Добавить наблюдение'));
    const pick = App.laserLensPicker(lists, {device: ctx.query.device, lens: ctx.query.lens, onChange: () => { location.hash = '#/colors?' + pick.route(); }});
    const [map, know] = await Promise.all([get('/color-model?' + pick.query()), get('/knowledge?' + pick.query())]);
    const head = h('div', {class: 'os-head lm-head'}, h('a', {class: 'btn btn-small', href: '#/colors'}, '← Карта цветов'),
      h('div', {class: 'lm-title'}, h('h2', {}, 'Карта цветов и подбор параметров'), h('p', {class: 'sub'}, 'Данные разных лазеров и линз (в том числе неизвестной) не объединяются.')),
      h('span', {class: 'spacer'}), h('div', {class: 'lm-pick'}, field('Лазер', pick.laser), field('Линза', pick.lens)),
      btn('Целевой цвет', () => predictDialog(pick), 'primary'), h('a', {class: 'btn btn-small', href: '#/designer?' + pick.route()}, 'Спланировать эксперимент'));
    const relativeSets = map.camera_relative_sets || [];
    if (!map.samples.length && !relativeSets.length) return h('div', {class: 'os lm'}, head,
      h('div', {class: 'card empty'}, h('h3', {}, 'Для этого лазера с этой линзой пока нет проверенных измерений'), link('/ingest', 'Добавить фото эксперимента')));

    // the sets in the order of the old page: the calibrated observations, then every RAW pair
    const sets = [...(map.samples.length ? [{id: 'calibrated', title: 'Калиброванные наблюдения', note: `измеренных цветов ${map.samples.length}${know.length ? ` · в модели ${know.length}` : ''}`, view: () => calibratedView(map, know, 'lm.knowledge.' + pick.route())}] : []),
      ...relativeSets.map((set) => ({id: 'pair-' + set.pair_id, title: `${set.provisional ? 'Предварительно · ' : ''}пара ${set.pair_id}`,
        note: `${set.photo_name || 'фото'} · слоёв ${(set.samples || []).length} · вариантов ${(set.color_variants || []).length}`, view: () => relativeView(set)}))];
    const left = h('section', {class: 'os-col lm-left', 'aria-label': 'Наборы наблюдений'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Наборы'), pill(sets.length)), h('div', {class: 'os-scroll'}, h('div', {class: 'lm-sets'})));
    const centre = h('section', {class: 'os-col lm-centre'}), right = h('section', {class: 'os-col lm-right'});
    const buttons = new Map(sets.map((s) => [s.id, h('button', {type: 'button', class: 'lm-set', 'aria-pressed': 'false', onClick: () => select(s.id)}, h('strong', {}, s.title), h('span', {class: 'muted small'}, s.note))]));
    left.querySelector('.lm-sets').append(...buttons.values());

    function select(id) {
      const set = sets.find((s) => s.id === id) || sets[0];
      for (const [key, node] of buttons) {
        node.setAttribute('aria-pressed', String(key === set.id));
        if (key === set.id) node.classList.add('active'); else node.classList.remove('active');
      }
      keep(SET_KEY, set.id);
      const view = set.view();
      fill(centre, h('div', {class: 'os-col-head'}, h('div', {class: 'lm-set-title'}, h('h3', {}, view.title), h('p', {class: 'muted small'}, view.sub)), view.plotTitle ? pill(view.plotTitle) : null),
        h('div', {class: 'lm-stage'}, h('div', {class: 'lm-plot'}, view.plot), h('div', {class: 'lm-alerts'}, ...view.alerts)));
      if (view.model) {
        fill(right, h('div', {class: 'os-col-head'}, h('h3', {}, 'Модель цветовых параметров'), pill(view.model.count)), h('div', {class: 'os-scroll'}, view.model.body));
      } else {
        const tabs = App.tabs(view.tabs, {initial: view.tabs[0][0], remember: TAB_KEY, label: 'Таблицы набора', prefix: 'lm-tab'});
        fill(right, tabs.list, h('div', {class: 'os-scroll'}, ...tabs.panels));
      }
    }
    select(sets.some((s) => s.id === stored(SET_KEY)) ? stored(SET_KEY) : sets[0].id);
    return h('div', {class: 'os lm'}, head,
      map.unstable.length ? h('div', {class: 'alert warn lm-unstable'}, 'Нестабильные наборы: ' + map.unstable.map((u) => `${u.parameters.power}/${u.parameters.frequency}/${u.parameters.speed}`).join(', ')) : null,
      h('div', {class: 'os-body lm-body'}, left, centre, right));
  }});
})();
