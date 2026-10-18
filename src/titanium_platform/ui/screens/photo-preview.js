/* Предпросмотр фотогравировки (REQ-030, DEC-057, DEC-062): как картинка слоя в режиме Grayscale выйдет на титане при заданных
   Min и Max мощности — по измеренной кривой «мощность → цвет» этого режима (лазер, линза, титан, скорость, частота, импульс, шаг,
   проходы). Серый картинки задаёт мощность линейно между Min (светлый) и Max (тёмный); мощность вне измеренного диапазона не
   прогнозируется и заштрихована. Файл загружается один раз: ползунки Min и Max перерисовывают прогноз из той же загрузки.
   Адрес: #/photo-preview; ?pair=<id> — файл принятой работы уже выбран вместе с её лазером, линзой и титаном. */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, form, num, swatch, labText, table} = App;
  const REFERENCE = {chart: ['по эталонной карте', 'ok'], 'clean titanium': ['относительно камеры, приведены к чистому титану своего снимка', 'warn'],
    'as photographed': ['относительно камеры, как сняты', 'warn']};
  const SOURCE_REFERENCE = {chart: 'по карте', 'clean titanium': 'к чистому титану', 'as photographed': 'как снят'};
  const OVERRIDES = [['min_power', 'Мин. мощность, %'], ['max_power', 'Макс. мощность, %'], ['speed', 'Скорость, мм/с'], ['frequency', 'Частота, кГц'],
    ['pulse_width', 'Длительность импульса, нс'], ['line_interval', 'Шаг линий, мм'], ['passes', 'Проходы']];
  const value = (v, d = 2) => (v == null ? '—' : String(+(+v).toFixed(d)));
  const materialLabel = (m) => [m.name, m.grade, m.thickness_mm != null ? `${m.thickness_mm} мм` : null, m.batch].filter(Boolean).join(' · ');

  function sourceLine(s) {
    return h('div', {class: 'small'}, link('/experiment/' + encodeURIComponent(s.experiment), s.title), ' · ',
      s.layer_name || `слой ${s.layer}`, ' · ', s.how === 'tonal profile' ? `тональный профиль, серый ${value(s.gray)}` : 'заливка', ' · ',
      `фото ${s.photo}`, ' · ', link(`/analysis/${s.pair_id}`, 'разбор'), ' ',
      pill(SOURCE_REFERENCE[s.reference] || s.reference, s.reference === 'chart' ? 'ok' : 'warn'));
  }

  function curveTable(info) {
    return table(['Серый картинки', 'Мощность, %', 'Измеренный цвет', 'Где измерен'], info.curve.points.map((p) => [
      p.grey == null ? h('span', {class: 'muted'}, 'вне Min–Max') : value(p.grey, 3), value(p.power),
      h('span', {}, swatch(p.lab), labText(p.lab)), h('div', {class: 'stack'}, p.sources.map(sourceLine))]));
  }

  function restsOn(info) {
    const s = info.mode, experiments = new Set(info.curve.points.flatMap((p) => p.sources.map((x) => x.experiment)));
    const [reference] = REFERENCE[info.reference] || [info.reference];
    return h('div', {class: 'stack'},
      h('p', {}, h('strong', {}, 'На чём основан прогноз. '),
        `Измеренные мощности этого режима: ${info.curve.points.length}, от ${value(info.span[0])} до ${value(info.span[1])} %, `
        + `из экспериментов: ${experiments.size}. Цвета ${reference}. Режим: ${value(s.speed, 1)} мм/с · ${value(s.frequency, 1)} кГц · `
        + `${s.pulse_width == null ? 'импульс не указан' : value(s.pulse_width, 0) + ' нс'} · шаг ${value(s.line_interval, 4)} мм · `
        + `проходов ${s.passes ?? '—'}${s.global_passes > 1 ? ` · глобально ${s.global_passes}×` : ''}. `
        + 'Серый картинки становится мощностью линейно: самый светлый — Min, самый тёмный — Max; цвет между измеренными мощностями — линейно в Lab.'),
      h('p', {}, h('strong', {}, 'Чего прогноз не знает. '),
        info.outside_share > 0 ? `${value(info.outside_share * 100, 1)} % картинки требует мощности вне измеренного диапазона: там прогноза нет, эти места заштрихованы. `
          : 'Вся картинка лежит в измеренном диапазоне мощностей. ',
        'Растрирование и ход луча не моделируются: показан цвет при мощности, которую задаёт серый.'),
      h('ul', {class: 'small'}, info.notes.map((n) => h('li', {}, I18N.tr(n)))));
  }

  function layerCard(layer, cacheId) {
    const head = h('div', {class: 'row'}, h('h3', {}, `Слой ${layer.name}`), pill(layer.dither || 'режим не указан'),
      (layer.settings.overridden || []).length ? pill('настройки изменены', 'warn') : null);
    if (layer.refused) return h('section', {class: 'card stack'}, head, h('div', {class: 'alert warn', role: 'status'}, I18N.tr(layer.refused)));
    const img = h('img', {class: 'pp-image', alt: `Картинка слоя ${layer.name} и её прогноз на титане`});
    const banner = h('div', {class: 'pp-banner', role: 'note'});
    const lost = h('div', {class: 'alert warn', role: 'status', hidden: true}, 'Предпросмотр больше не хранится: загрузите файл ещё раз.');
    img.addEventListener('error', () => { lost.hidden = false; });
    img.addEventListener('load', () => { lost.hidden = true; });
    const about = h('div', {class: 'stack'}), curve = h('div', {});
    const slider = (key, label) => {
      const range = h('input', {type: 'range', min: 0, max: 100, step: 0.1, value: layer.settings[key], 'aria-label': label});
      const exact = h('input', {type: 'number', min: 0, max: 100, step: 'any', value: layer.settings[key], 'aria-label': label, style: 'width:6em'});
      range.addEventListener('input', () => { exact.value = range.value; schedule(); });
      exact.addEventListener('change', () => { range.value = exact.value; schedule(); });
      return {exact, box: h('label', {class: 'f'}, h('span', {}, label), h('span', {class: 'row'}, range, exact))};
    };
    const low = slider('min_power', 'Мин. мощность, %'), high = slider('max_power', 'Макс. мощность, %');
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});

    function draw(info) {
      const lo = +low.exact.value, hi = +high.exact.value;
      img.src = `${info.preview}?min_power=${lo}&max_power=${hi}`;
      // DEC-062: a prediction from camera-relative colours says so on the picture itself
      banner.hidden = info.referenced;
      banner.textContent = info.referenced ? '' : 'Цвета относительно камеры: такими их увидела камера при том освещении, без коррекции по эталонной карте'
        + (info.reference === 'as photographed' ? '; чистого титана на снимке нет — цвета как сняты.' : '; приведены к чистому титану своего снимка.');
      fill(about, restsOn(info));
      fill(curve, h('h4', {}, 'Кривая «мощность → цвет» этого режима'), curveTable(info));
    }
    let timer = null, seq = 0;
    async function rerender() {
      const lo = +low.exact.value, hi = +high.exact.value;
      error.hidden = true;
      if (!(lo <= hi)) { error.textContent = 'Мин. мощность должна быть не выше макс.'; error.hidden = false; return; }
      const mine = ++seq;
      try {
        const info = await get(`/predictions/photo/${cacheId}/${layer.index}?min_power=${lo}&max_power=${hi}`);
        if (mine === seq) draw(info);
      } catch (e) { error.textContent = e.message; error.hidden = false; }
    }
    function schedule() { clearTimeout(timer); timer = setTimeout(rerender, 250); }
    draw(layer);
    return h('section', {class: 'card stack'}, head,
      h('div', {class: 'grid g2'}, low.box, high.box), error, lost,
      h('div', {class: 'pp-captions'}, h('span', {}, 'Картинка из файла'), h('span', {}, 'Прогноз на титане')),
      h('div', {class: 'pp-stage'}, img, banner),
      about, curve);
  }

  App.register({id: 'photo-preview', async render(ctx) {
    const [lists, materials] = await Promise.all([App.hardwareLists(), get('/materials')]);
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер'), link('/devices', 'Лазеры'));
    let preloaded = null;                       // the LightBurn file of an accepted work, opened from its experiment
    if (ctx.query.pair) {
      const pair = await get('/pairs/' + encodeURIComponent(ctx.query.pair));
      const blob = await get(`/pairs/${pair.id}/lightburn`);
      preloaded = {file: new File([blob], pair.lightburn_name), pair};
    }
    const pick = App.laserLensPicker(lists, {device: preloaded ? preloaded.pair.device_id : ctx.query.device,
      lens: preloaded ? App.lensParam(preloaded.pair.lens_id) : ctx.query.lens, defaultLens: 'installed'});
    const mat = h('select', {'aria-label': 'Титан'}, h('option', {value: ''}, 'выберите титан'), materials.map((m) => h('option', {value: m.id}, materialLabel(m))));
    const wantedMaterial = preloaded ? preloaded.pair.material_id : ctx.query.material;
    if (wantedMaterial != null && materials.some((m) => String(m.id) === String(wantedMaterial))) mat.value = String(wantedMaterial);
    const fileIn = h('input', {type: 'file', accept: '.lbrn,.lbrn2', 'aria-label': 'Файл LightBurn'});
    const fileNote = h('p', {class: 'muted small'}, preloaded ? `Файл работы «${preloaded.pair.lightburn_name}» уже выбран: можно выбрать другой.` : '');
    const overrides = OVERRIDES.map(([key, label]) => [key, h('input', {type: 'number', step: 'any', placeholder: 'как в файле', 'aria-label': label})]);
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const results = h('div', {class: 'stack'});

    async function predict() {
      error.hidden = true;
      const file = fileIn.files[0] || (preloaded && preloaded.file);
      if (!file) { error.textContent = 'Выберите файл LightBurn'; error.hidden = false; return; }
      if (!mat.value) { error.textContent = 'Выберите титан: кривая строится по измерениям на этом титане'; error.hidden = false; return; }
      const fd = new FormData();
      fd.append('device_id', pick.deviceId()); fd.append('lens_id', pick.lensValue()); fd.append('material_id', mat.value);
      for (const [key, input] of overrides) if (input.value !== '') fd.append(key, input.value);
      fd.append('lightburn', file, file.name);
      fill(results, h('p', {class: 'muted'}, 'Считаем прогноз…'));
      try {
        const out = await form('/predictions/photo', fd);
        fill(results, h('p', {class: 'muted small'}, `Файл «${out.file}» · слоёв изображения: ${out.layers.length}. Ползунки Min и Max перерисовывают прогноз без новой загрузки.`),
          ...out.layers.map((layer) => layerCard(layer, out.cache_id)));
      } catch (e) { fill(results); error.textContent = e.message; error.hidden = false; }
    }
    if (preloaded) predict();
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Предпросмотр фотогравировки'),
        h('p', {class: 'sub'}, 'Как картинка слоя Grayscale выйдет на титане при заданных Min и Max мощности — по измеренной кривой «мощность → цвет» этого режима.')),
        h('span', {class: 'spacer'}), link('/photo', 'Фотогравировка'), link('/colors', 'Карта цветов')),
      h('div', {class: 'card stack'},
        h('div', {class: 'grid g2'}, field('Файл LightBurn', App.filePick(fileIn, 'Выбрать файл')), field('Титан', mat),
          field('Лазер', pick.laser), field('Линза', pick.lens, 'кривая строится по измерениям этого лазера с этой линзой')),
        fileNote,
        h('details', {}, h('summary', {class: 'small'}, 'Другие настройки слоя (необязательно; пусто — как в файле)'),
          h('div', {class: 'grid g3'}, overrides.map(([key, input]) => field(OVERRIDES.find((o) => o[0] === key)[1], input)))),
        error, h('div', {class: 'toolbar'}, btn('Показать прогноз', predict, 'primary'))),
      results);
  }});
})();
