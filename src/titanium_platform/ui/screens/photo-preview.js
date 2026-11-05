/* Предпросмотр фотогравировки (REQ-030, DEC-057, DEC-062): как картинка слоя в режиме Grayscale выйдет на титане при заданных
   Min и Max мощности — по измеренной кривой «мощность → цвет» этого режима (лазер, линза, титан, скорость, частота, импульс, шаг,
   проходы). Серый картинки задаёт мощность линейно между Min (светлый) и Max (тёмный); мощность вне измеренного диапазона не
   прогнозируется и заштрихована. Файл загружается один раз: ползунки Min и Max перерисовывают прогноз из той же загрузки.
   Адрес: #/photo-preview; ?pair=<id> — файл принятой работы уже выбран вместе с её лазером, линзой и титаном; ?work=<id> — так же файл
   фотоработы (её шкала даёт лазер, линзу и титан). */
'use strict';
(() => {
  const {h, fill, btn, link, pill, get, form, num, swatch, labText, table} = App;
  const REFERENCE = {chart: ['по эталонной карте', 'ok'], 'clean titanium': ['относительно камеры, приведены к чистому титану своего снимка', 'warn'],
    'as photographed': ['относительно камеры, как сняты', 'warn']};
  const SOURCE_REFERENCE = {chart: 'по карте', 'clean titanium': 'к чистому титану', 'as photographed': 'как снят'};
  const SPREAD_LIMIT = 5;                     // ΔE within which independent engravings agree (agreement.AGREEMENT_DE, DEC-083)
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

  const TONE = (info) => info.axis === 'darkness';       // a dot mode: the curve runs over the darkness of the grey, not over a power

  const spreadCell = (p) => (p.spread_de == null ? h('span', {class: 'muted'}, p.engravings === 1 ? 'одна гравировка' : '—')
    : h('span', {}, pill(`${value(p.spread_de, 1)} ΔE`, p.spread_de > SPREAD_LIMIT ? 'warn' : 'ok'), ` · гравировок ${p.engravings}`));

  function curveTable(info) {
    const tone = TONE(info);
    return table(['Серый картинки', tone ? 'Тон (темнота серого), %' : 'Мощность, %', 'Измеренный цвет', 'Расхождение гравировок', 'Где измерен'], info.curve.points.map((p) => [
      p.grey == null ? h('span', {class: 'muted'}, tone ? 'вне картинки' : 'вне Min–Max') : value(p.grey, 3), value(p.power),
      h('span', {}, swatch(p.lab), labText(p.lab)), spreadCell(p), h('div', {class: 'stack'}, p.sources.map(sourceLine))]));
  }

  function restsOn(info) {
    const s = info.mode, experiments = new Set(info.curve.points.flatMap((p) => p.sources.map((x) => x.experiment)));
    const [reference] = REFERENCE[info.reference] || [info.reference];
    const tone = TONE(info);
    const pictureMode = `${value(s.speed, 1)} мм/с · ${value(s.frequency, 1)} кГц · `
      + `${s.pulse_width == null ? 'импульс не указан' : value(s.pulse_width, 0) + ' нс'} · шаг ${value(s.line_interval, 4)} мм · `
      + `проходов ${s.passes ?? '—'}${s.global_passes > 1 ? ` · глобально ${s.global_passes}×` : ''}`
      + (tone ? ` · мощность точек ${value(s.power, 1)} %${s.dot_width != null ? ` · ширина точки ${value(s.dot_width, 3)} мм` : ''}` : '');
    return h('div', {class: 'stack'},
      h('p', {}, h('strong', {}, 'На чём основан прогноз. '),
        `Измеренные ${tone ? 'тона' : 'мощности'} этого режима: ${info.curve.points.length}, от ${value(info.span[0])} до ${value(info.span[1])} %, `
        + `из экспериментов: ${experiments.size}. Цвета ${reference}. Режим: ${pictureMode}. `
        + (tone ? 'Серый картинки задаёт плотность точек, каждая бьёт на мощности слоя; цвет между измеренными тонами — линейно в Lab.'
          : 'Серый картинки становится мощностью линейно: самый светлый — Min, самый тёмный — Max; цвет между измеренными мощностями — линейно в Lab.')),
      h('p', {}, h('strong', {}, 'Чего прогноз не знает. '),
        info.outside_share > 0 ? `${value(info.outside_share * 100, 1)} % картинки требует ${tone ? 'тона' : 'мощности'} вне измеренного диапазона: там прогноза нет, эти места заштрихованы. `
          : `Вся картинка лежит в измеренном диапазоне ${tone ? 'тонов' : 'мощностей'}. `,
        tone ? 'Растрирование не моделируется: цвет тона — то, что сфотографировано при этом тоне в этом режиме и на этих настройках.'
          : 'Растрирование и ход луча не моделируются: показан цвет при мощности, которую задаёт серый.',
        info.spread && info.spread.max_de != null ? ` Независимые гравировки этого режима расходятся до ${value(info.spread.max_de, 0)} ΔE; на ${value(info.spread.uncertain * 100, 0)} % предсказанной картинки — больше ${SPREAD_LIMIT} ΔE: читайте цвет там как диапазон.` : ''),
      h('ul', {class: 'small'}, info.notes.map((n) => h('li', {}, I18N.tr(n)))));
  }

  function layerCard(layer, cacheId, elsewhere) {
    const head = h('div', {class: 'row'}, h('h3', {}, `Слой ${layer.name}`), pill(layer.dither ? PhotoModes.label(layer.dither) : 'режим не указан'),
      (layer.settings.overridden || []).length ? pill('настройки изменены', 'warn') : null);
    if (layer.refused) return h('section', {class: 'card stack'}, head, h('div', {class: 'alert warn', role: 'status'}, I18N.tr(layer.refused)), elsewhere(layer));
    const img = h('img', {class: 'pp-image', alt: `Картинка слоя ${layer.name} и её прогноз на титане`});
    const banner = h('div', {class: 'pp-banner', role: 'note'});
    const lost = h('div', {class: 'alert warn', role: 'status', hidden: true}, 'Предпросмотр больше не хранится: загрузите файл ещё раз.');
    img.addEventListener('error', () => { lost.hidden = false; });
    img.addEventListener('load', () => { lost.hidden = true; });
    const about = h('div', {class: 'stack'}), curve = h('div', {});
    const slider = (key, label) => {
      const range = h('input', {type: 'range', min: 0, max: 100, step: 0.1, value: layer.settings[key], 'aria-label': label});
      const exact = h('input', {type: 'number', min: 0, max: 100, step: 'any', value: layer.settings[key], 'aria-label': label, style: 'width:6em'});
      range.addEventListener('input', () => { exact.value = range.value; exact.removeAttribute('aria-invalid'); note.textContent = ''; schedule(); });
      // prediction_store.check_power_range: 0 to 100 %; a value outside is kept in the box with the reason beside it and is not applied
      const note = Forms.watch(exact, 'photoPower', (v) => { range.value = v; schedule(); });
      return {exact, box: h('div', {class: 'stack'}, h('label', {class: 'f'}, h('span', {}, label), h('span', {class: 'row'}, range, exact)), note)};
    };
    const tone = TONE(layer);
    const low = slider('min_power', 'Мин. мощность, %'), high = slider('max_power', 'Макс. мощность, %');
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});

    function draw(info) {
      const lo = +low.exact.value, hi = +high.exact.value;
      img.src = tone ? info.preview : `${info.preview}?min_power=${lo}&max_power=${hi}`;
      // DEC-062: a prediction from camera-relative colours says so on the picture itself
      banner.hidden = info.referenced;
      banner.textContent = info.referenced ? '' : 'Цвета относительно камеры: такими их увидела камера при том освещении, без коррекции по эталонной карте'
        + (info.reference === 'as photographed' ? '; чистого титана на снимке нет — цвета как сняты.' : '; приведены к чистому титану своего снимка.');
      fill(about, restsOn(info));
      fill(curve, h('h4', {}, tone ? 'Кривая «тон → цвет» этого режима' : 'Кривая «мощность → цвет» этого режима'), curveTable(info));
    }
    let timer = null, seq = 0;
    async function rerender() {
      const bounds = [low, high].map((b) => Forms.readNumber(b.exact, Forms.QUANTITIES.photoPower, {required: true}));
      error.hidden = true;
      if (tone || !bounds.every((b) => b.ok)) return;                    // a wrong box keeps its text and says why beside itself
      const [lo, hi] = bounds.map((b) => b.value);
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
      tone ? h('p', {class: 'muted small'}, 'В этом режиме каждая точка бьёт на мощности слоя: Min и Max не меняют результат, ползунков нет. Другая мощность — другой режим, его нужно измерить отдельно.')
        : h('div', {class: 'grid g2'}, low.box, high.box), error, lost,
      h('div', {class: 'pp-captions'}, h('span', {}, 'Картинка из файла'), h('span', {}, 'Прогноз на титане')),
      h('div', {class: 'pp-stage'}, img, banner),
      about, curve);
  }

  App.register({id: 'photo-preview', async render(ctx) {
    const lists = await App.hardwareLists();
    if (!lists.devices.length) return h('div', {class: 'card empty'}, h('h3', {}, 'Сначала добавьте лазер'), link('/devices', 'Лазеры'));
    let preloaded = null;                       // the LightBurn file of an accepted work, opened from its experiment, or of a photo work
    if (ctx.query.pair) {
      const pair = await get('/pairs/' + encodeURIComponent(ctx.query.pair));
      const blob = await get(`/pairs/${pair.id}/lightburn`);
      preloaded = {file: new File([blob], pair.lightburn_name), pair};
    } else if (ctx.query.work) {
      const work = (await get('/photo-works')).find((w) => String(w.id) === String(ctx.query.work));
      if (work) {
        const name = `${work.name}-P${work.min_power}-${work.max_power}.lbrn2`;
        const blob = await get(`/photo-works/${work.id}/export.lbrn2`);
        preloaded = {file: new File([blob], name),
          pair: {device_id: work.scale.device_id, lens_id: work.scale.lens_id, material_id: work.scale.material_id, lightburn_name: name}};
      }
    }
    const pick = App.laserLensPicker(lists, {device: preloaded ? preloaded.pair.device_id : ctx.query.device,
      lens: preloaded ? App.lensParam(preloaded.pair.lens_id) : ctx.query.lens, defaultLens: 'installed'});
    const form_ = Forms.create();
    // one concrete record, found by a search among the records used last and not in a list of all; none is chosen unless the file's work or the address names one
    // (ux-growing-collections-p0, REQ-001)
    const wantedMaterial = preloaded ? preloaded.pair.material_id : ctx.query.material;
    const mat = MaterialPicker.create({value: wantedMaterial, allowEmpty: true, clearLabel: 'Снять выбор', empty: 'выберите титан', name: 'Титан'});
    const fileIn = h('input', {type: 'file', accept: '.lbrn,.lbrn2'});
    const fileNote = h('p', {class: 'muted small'}, preloaded ? `Файл работы «${preloaded.pair.lightburn_name}» уже выбран: можно выбрать другой.` : '');
    // the form: the file, the titanium and the laser are required; each override is a number or empty («as in the file»). The ranges are the server's where it
    // has them (the powers: prediction_store.check_power_range; the passes: a whole number from 1); the other overrides are only checked to be numbers
    const OVERRIDE_QUANTITY = {min_power: 'photoPower', max_power: 'photoPower', passes: 'passes'};
    const fileField = form_.add('file', 'Файл LightBurn', App.filePick(fileIn, 'Выбрать файл'), {required: true,
      read: () => { const f = fileIn.files[0] || (preloaded && preloaded.file); return f ? {ok: true, value: f} : {ok: false, message: 'Выберите файл LightBurn'}; }});
    const matField = form_.add('material', 'Титан', mat, {required: true,
      read: () => (mat.value ? {ok: true, value: mat.value} : {ok: false, message: 'Выберите титан: кривая строится по измерениям на этом титане'})});
    const laserField = form_.add('laser', 'Лазер', pick.laser, {required: true,
      read: () => (pick.deviceId() ? {ok: true, value: pick.deviceId()} : {ok: false, message: 'Выберите лазер'})});
    const lensField = form_.add('lens', 'Линза', pick.lens, {help: 'кривая строится по измерениям этого лазера с этой линзой', read: () => ({ok: true, value: pick.lensValue()})});
    const overrides = OVERRIDES.map(([key, label]) => [key, form_.add(key, label, Forms.numberInput(Forms.QUANTITIES[OVERRIDE_QUANTITY[key]] || null, {placeholder: 'как в файле'}),
      OVERRIDE_QUANTITY[key] ? {quantity: OVERRIDE_QUANTITY[key]} : {})]);
    const results = h('div', {class: 'stack'});

    async function predict() {
      const v = form_.collect();
      if (!v) return;
      const file = v.file;
      const fd = new FormData();
      fd.append('device_id', v.laser); fd.append('lens_id', v.lens); fd.append('material_id', v.material);
      for (const [key] of overrides) if (v[key] != null) fd.append(key, v[key]);
      fd.append('lightburn', file, file.name);
      fill(results, h('p', {class: 'muted'}, 'Считаем прогноз…'));
      try {
        const out = await form('/predictions/photo', fd);
        await knowStocks(out.layers);
        fill(results, h('p', {class: 'muted small'}, `Файл «${out.file}» · слоёв изображения: ${out.layers.length}. Ползунки Min и Max перерисовывают прогноз без новой загрузки.`),
          ...out.layers.map((layer) => layerCard(layer, out.cache_id, elsewhere)));
      } catch (e) { fill(results); form_.fail(e); }
    }
    /* Where the file's mode is measured, when the chosen laser, lens and titanium have no measurement of it: one button each switches to it. */
    const known = new Map();                                     // titanium id -> its record, read one by one for the lines below (never the whole catalogue)
    const knowStocks = async (layers) => {
      const wanted = [...new Set(layers.flatMap((layer) => (layer.measured_on || []).map((m) => m.material_id)).filter((id) => id != null && !known.has(id)))];
      await Promise.all(wanted.map(async (id) => { try { known.set(id, await MaterialPicker.one(id)); } catch (_) { /* the line says «титан не указан» */ } }));
    };
    const setupLabel = (m) => {
      const d = lists.devices.find((x) => x.id === m.device_id), l = lists.lenses.find((x) => x.id === m.lens_id), t = known.get(m.material_id);
      return [t ? materialLabel(t) : 'титан не указан', d ? (d.title || d.name) : `лазер ${m.device_id}`, l ? App.lensLabel(l) : 'линза неизвестна'].join(' · ');
    };
    function switchTo(m) {
      pick.laser.value = String(m.device_id);
      pick.setLens(m.lens_id);
      mat.value = m.material_id == null ? '' : String(m.material_id);
      predict();
    }
    function elsewhere(layer) {
      const found = layer.measured_on;
      if (found == null) return null;
      if (!found.length) return h('p', {class: 'muted small'}, 'Этот режим не измерен ни на одном титане, лазере и линзе: нужна гравировка шкалы серого с этими настройками.');
      return h('div', {class: 'stack'}, h('p', {class: 'small'}, 'Этот режим измерен здесь:'),
        ...found.map((m) => h('div', {class: 'row'}, h('span', {class: 'small'}, setupLabel(m)), btn('Показать на нём', () => switchTo(m), 'btn-small'))));
    }
    if (preloaded) predict();
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Предпросмотр фотогравировки'),
        h('p', {class: 'sub'}, 'Как картинка слоя-изображения выйдет на титане: в режиме градаций серого — при заданных Min и Max по измеренной кривой «мощность → цвет»; '
          + 'в режимах точек (Джарвис, Стаки и другие) — по тонам, измеренным в том же режиме. Там, где независимые гравировки расходятся, это видно.')),
        h('span', {class: 'spacer'}), link('/photo', 'Фотогравировка'), link('/colors', 'Карта цветов')),
      h('div', {class: 'card stack'},
        h('div', {class: 'grid g2'}, fileField, matField, laserField, lensField),
        fileNote,
        h('details', {}, h('summary', {class: 'small'}, 'Другие настройки слоя (необязательно; пусто — как в файле)'),
          h('div', {class: 'grid g3'}, overrides.map(([, fieldEl]) => fieldEl))),
        form_.error, h('div', {class: 'toolbar'}, btn('Показать прогноз', predict, 'primary'))),
      results);
  }});
})();
