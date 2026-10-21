/* Фотогравировка (REQ-059): режим градаций серого по измеренным шкалам. Шкала — постоянные настройки (лазер, линза, титан, скорость,
   частота, импульс, шаг строк, проходы) с измеренной кривой «мощность → цвет»; серый картинки задаёт мощность от Min (белый) до Max
   (чёрный), и на титане мощность даёт цвет. Здесь видно, какой серый каким цветом выходит при выбранных Min и Max, подтверждают ли это
   эксперименты, как выйдет картинка, сколько она гравируется, и скачивается файл LightBurn с этими настройками.
   Адрес: #/photo-engraving; другие виды — #/photo-preview (прогноз по файлу LightBurn) и #/photo (непрерывная полосами). */
'use strict';
(() => {
  const {h, fill, btn, field, link, pill, get, form, labText, duration, table, fail} = App;
  const SPREAD_LIMIT = 5;                       // ΔE within which independent engravings agree (agreement.AGREEMENT_DE, DEC-083)
  const BAR_SEGMENTS = 64;                      // segments of the grey -> colour bar (4 grey levels each)
  const TABLE_STEP = 17;                        // the 16 greys of the table: 255, 238, ... 0, the steps of the plate's ramp
  const value = (v, d = 2) => (v == null ? '—' : String(+(+v).toFixed(d)).replace('.', ','));
  const materialLabel = (m) => (m ? [m.name, m.grade, m.thickness_mm != null ? `${m.thickness_mm} мм` : null, m.batch].filter(Boolean).join(' · ') : 'титан не указан');
  const HOW = {'grey ramp': 'пластина шкал серого', 'tonal profile': 'фотогравировка'};
  const REFERENCE = {chart: ['цвета по эталонной карте', 'ok'], 'clean titanium': ['цвета относительно камеры, приведены к чистому титану', 'warn'],
    'as photographed': ['цвета относительно камеры, как сняты', 'warn']};

  const settingsText = (m, dpi) => `${value(m.speed, 1)} мм/с · ${value(m.frequency, 1)} кГц · ${m.pulse_width == null ? 'импульс не указан' : value(m.pulse_width, 0) + ' нс'}`
    + ` · шаг ${value(m.line_interval, 4)} мм${dpi ? ` (${dpi} dpi)` : ''} · проходов ${m.passes ?? 1}${m.global_passes > 1 ? ` · глобально ${m.global_passes}×` : ''}`;
  const modeQuery = (m) => new URLSearchParams(Object.entries({device_id: m.device_id, lens_id: App.lensParam(m.lens_id), material_id: m.material_id,
    speed: m.speed, frequency: m.frequency, pulse_width: m.pulse_width, line_interval: m.line_interval, passes: m.passes ?? 1, global_passes: m.global_passes ?? 1})
    .filter(([, v]) => v != null)).toString();
  const greyChip = (level) => h('span', {class: 'sw', style: `background:rgb(${level},${level},${level})`});
  const hexChip = (hex) => (hex ? h('span', {class: 'sw', style: `background:${hex}`}) : h('span', {class: 'sw ge-none', title: 'не измерено'}));

  function confirmationPill(c) {
    if (!c || c.median_de == null) return pill(c && c.engravings > 1 ? 'гравировки не пересекаются по мощности' : 'одна гравировка: подтвердить нечем', 'warn');
    return pill(`${c.confirmed ? 'подтверждена' : 'не подтверждена'}: медиана ${value(c.median_de, 1)} ΔE`, c.confirmed ? 'ok' : 'warn');
  }

  /** Карточка шкалы в списке: цвета по измеренным мощностям, настройки, чем измерена, подтверждение и время на см². */
  function scaleCard(sc, chosen, choose) {
    const bar = sc.bar.length ? `linear-gradient(to right, ${sc.bar.map((b) => b.hex).join(', ')})` : 'none';
    const kinds = Object.entries(sc.by_kind).map(([how, n]) => `${HOW[how] || how}: ${n}`).join(' · ');
    return h('button', {type: 'button', class: 'ge-scale' + (chosen ? ' is-chosen' : ''), 'aria-pressed': String(chosen), onClick: choose},
      h('span', {class: 'ge-bar', style: `background:${bar}`}),
      h('span', {class: 'ge-ends small'}, h('span', {}, `P ${value(sc.span[0], 1)} %`), h('span', {}, `P ${value(sc.span[1], 1)} %`)),
      h('strong', {}, settingsText(sc.mode, sc.dpi)),
      h('span', {class: 'small muted'}, `${materialLabel(sc.material)} · ${kinds} · ${value(sc.time_s_per_cm2, 0)} с/см²`),
      h('span', {class: 'row'}, confirmationPill(sc.confirmation), pill(...(REFERENCE[sc.reference] || [sc.reference]))));
  }

  /** Полоса «серый → цвет» при выбранных Min и Max: слева белый (Min), справа чёрный (Max), как ступени пластины; вне измеренного — штриховка. */
  function greyBar(levels) {
    const at = (i) => levels[255 - Math.round(i * 255 / (BAR_SEGMENTS - 1))];
    const segments = Array.from({length: BAR_SEGMENTS}, (_, i) => at(i));
    return h('div', {class: 'stack ge-greybar'},
      h('div', {class: 'ge-strip', 'aria-label': 'Цвет каждого серого'}, segments.map((row) => h('span', {class: row.hex ? '' : 'ge-none',
        style: row.hex ? `background:${row.hex}` : '', title: `серый ${row.level} · мощность ${value(row.power)} %${row.hex ? '' : ' · не измерено'}`}))),
      h('div', {class: 'ge-strip ge-ramp', 'aria-hidden': 'true'}),
      h('div', {class: 'ge-ends small'}, h('span', {}, `белый 255 · Min ${value(levels[255].power, 1)} %`), h('span', {}, `чёрный 0 · Max ${value(levels[0].power, 1)} %`)));
  }

  function greyTable(levels) {
    const rows = [];
    for (let level = 255; level >= 0; level -= TABLE_STEP) {
      const r = levels[level];
      rows.push([h('span', {}, greyChip(level), ` ${level}`), value(r.power), r.lab ? h('span', {}, hexChip(r.hex), ' ', labText(r.lab)) : h('span', {class: 'muted'}, 'вне измеренных мощностей'),
        r.spread_de == null ? h('span', {class: 'muted'}, '—') : pill(`${value(r.spread_de, 1)} ΔE`, r.spread_de > SPREAD_LIMIT ? 'warn' : 'ok')]);
    }
    return table(['Серый картинки (0–255)', 'Мощность, %', 'Цвет на титане', 'Расхождение гравировок'], rows, '', true);
  }

  const sourceText = (s) => [s.title, HOW[s.how] || s.how, s.layer_name, s.photo ? `фото ${s.photo}` : null].filter(Boolean).join(' · ');

  function confirmationBlock(c) {
    const rows = c.rows.map((r) => [h('span', {}, link('/experiment/' + encodeURIComponent(r.engraving.experiment), r.engraving.title), ` · ${HOW[r.engraving.how] || r.engraving.how}`),
      String(r.points), r.compared ? String(r.compared) : h('span', {class: 'muted'}, 'нечем сравнить'),
      r.median_de == null ? '—' : pill(`${value(r.median_de, 1)} ΔE`, r.median_de > c.tolerance_de ? 'warn' : 'ok'), value(r.max_de, 1),
      r.within == null ? '—' : `${value(r.within * 100, 0)} %`]);
    return h('div', {class: 'stack'}, h('h4', {}, 'Подтверждают ли эксперименты'),
      h('p', {class: 'small'}, 'Каждая гравировка сравнивается со шкалой, построенной по всем остальным: на её мощностях — разница цвета. Подтверждена, если медиана не больше '
        + `${c.tolerance_de} ΔE. `, confirmationPill(c)),
      table(['Гравировка', 'Точек', 'Сравнено', 'Медиана', 'Максимум ΔE', `В пределах ${c.tolerance_de} ΔE`], rows, 'Нет гравировок', true));
  }

  function fillsBlock(fills) {
    if (!fills.length) return null;
    return h('details', {}, h('summary', {}, `Заливки с теми же настройками (${fills.length}) — для сравнения, в шкалу не входят`),
      h('p', {class: 'small muted'}, 'Заливка и серый картинки на той же мощности выходят разным цветом (на ваших данных — до 36 ΔE в светлой и средней части), поэтому шкала строится только по фотогравировкам и пластинам шкал серого.'),
      table(['Мощность, %', 'Цвет заливки', 'Разница со шкалой', 'Где'], fills.map((f) => [value(f.power), h('span', {}, hexChip(f.hex), ' ', labText(f.lab)),
        f.de == null ? h('span', {class: 'muted'}, f.curve_lab ? 'другой способ измерения' : 'вне шкалы') : pill(`${value(f.de, 1)} ΔE`, f.de > SPREAD_LIMIT ? 'warn' : 'ok'),
        sourceText(f.source)]), '', true));
  }

  function pointsBlock(curve) {
    return h('details', {}, h('summary', {}, `Измеренные точки шкалы (${curve.points.length})`),
      table(['Мощность, %', 'Цвет', 'Гравировок', 'Где измерено'], curve.points.map((p) => [value(p.power), h('span', {}, hexChip(p.hex), ' ', labText(p.lab)), String(p.engravings),
        h('div', {class: 'stack small'}, p.sources.map((s) => h('span', {}, link('/experiment/' + encodeURIComponent(s.experiment), s.title), ` · ${HOW[s.how] || s.how}`,
          s.gray != null ? ` · серый ${Math.round(s.gray * 255)}` : '', s.pair_id ? [' · ', link(`/analysis/${s.pair_id}`, 'разбор')] : null)))]), '', true));
  }

  /** Файл с сервера сохраняется на компьютер; ошибка сервера показывается переведённой, без перехода на адрес API. */
  async function download(path, fallbackName) {
    let res;
    try { res = await fetch('/api' + path); } catch (_) { throw new Error('Нет связи с локальным сервисом. Запущено ли приложение?'); }
    if (!res.ok) {
      let raw = null;
      try { const d = await res.json(); raw = (d.detail || d).error; } catch (_) { raw = null; }
      throw new Error(raw ? I18N.tr(raw) : `Ошибка сервера (${res.status}). Файл не получен.`);
    }
    const name = decodeURIComponent((res.headers.get('content-disposition') || '').split("UTF-8''")[1] || fallbackName);
    const url = URL.createObjectURL(await res.blob());
    const a = h('a', {href: url, download: name});
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(url);
  }

  /** Картинка на шкале: загрузка, прогноз рядом с картинкой, время для размера и файл LightBurn с этими Min и Max. */
  function pictureBlock(sc, powers) {
    const fileIn = h('input', {type: 'file', accept: 'image/png,image/jpeg,image/tiff,image/bmp,image/webp', 'aria-label': 'Картинка'});
    const width = h('input', {type: 'number', min: '1', max: '1000', step: 'any', value: '50', 'aria-label': 'Ширина на титане, мм', style: 'width:7em'});
    const byColour = h('input', {type: 'checkbox'});
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const out = h('div', {class: 'stack'});
    let cacheId = null, original = null, seq = 0;
    const show = (info) => {
      const outside = info.outside_share > 0 ? h('p', {class: 'alert warn'}, `${value(info.outside_share * 100, 1)} % картинки требует мощности вне измеренной шкалы: там прогноза нет, места заштрихованы.`) : null;
      const match = info.colour_match ? h('p', {}, h('strong', {}, 'Подбор по цвету: '), `ближайшие цвета шкалы отличаются от цветов картинки в среднем на ${value(info.colour_match.median_de, 1)} ΔE `
        + `(у 90 % пикселей — не больше ${value(info.colour_match.p90_de, 1)}); использовано серых ${info.colour_match.greys_used} из ${info.colour_match.greys_available}.`) : null;
      const t = info.time;
      fill(out,
        h('div', {class: 'pp-captions'}, h('span', {}, info.by_colour ? 'Подобранные серые' : 'Картинка (как её видит LightBurn)'), h('span', {}, 'Прогноз на титане')),
        h('div', {class: 'pp-stage'}, h('img', {class: 'pp-image', src: info.preview, alt: 'Картинка и её прогноз на титане'})),
        original && info.by_colour ? h('details', {}, h('summary', {class: 'small'}, 'Исходная цветная картинка'), h('img', {class: 'pp-image', src: original, alt: 'Исходная картинка'})) : null,
        h('p', {}, h('strong', {}, `Время гравировки: ≈ ${duration(t.seconds)}`),
          ` для ${value(info.size_mm.width, 1)} × ${value(info.size_mm.height, 1)} мм на шкале ${value(sc.time_s_per_cm2, 0)} с/см²`,
          h('span', {class: 'muted small'}, ' — оценка: строки на всю ширину картинки (в градациях серого бьёт и белый — на Min), скорость, шаг строк и проходы; разгон и переходы не учтены.')),
        match, outside,
        h('div', {class: 'row'}, btn('Скачать файл LightBurn', async (ev) => {
          const self = ev.currentTarget;
          self.disabled = true;
          try { await download(info.file.replace(/^\/api/, ''), 'picture.lbrn2'); } catch (e) { fail(e); } finally { self.disabled = false; }
        }, 'primary'), h('span', {class: 'muted small'}, `Один слой-изображение C00 в режиме градаций серого: Min ${value(info.power_range[0], 1)} %, Max ${value(info.power_range[1], 1)} %, `
          + `${settingsText(sc.mode, info.dpi)}. Картинка ${value(info.size_mm.width, 1)} мм в ширину, левый верхний угол в нуле.`)),
        h('ul', {class: 'small'}, info.notes.map((n) => h('li', {}, I18N.tr(n)))));
    };
    async function send() {
      error.hidden = true;
      const file = fileIn.files[0];
      if (!file) { error.textContent = 'Выберите картинку (PNG, JPEG, TIFF)'; error.hidden = false; return; }
      const [lo, hi] = powers();
      const fd = new FormData();
      for (const [k, v] of new URLSearchParams(modeQuery(sc.mode))) fd.append(k, v);
      fd.append('min_power', lo); fd.append('max_power', hi); fd.append('width_mm', width.value); fd.append('by_colour', byColour.checked ? 'true' : 'false');
      fd.append('picture', file, file.name);
      if (original) URL.revokeObjectURL(original);
      original = URL.createObjectURL(file);
      fill(out, h('p', {class: 'muted'}, 'Считаем прогноз…'));
      try { const info = await form('/grey-scales/picture', fd); cacheId = info.cache_id; show(info); }
      catch (e) { fill(out); error.textContent = e.message; error.hidden = false; }
    }
    async function rerender() {
      if (!cacheId) return;
      const [lo, hi] = powers();
      const mine = ++seq;
      try {
        const info = await get(`/grey-scales/picture/${cacheId}?min_power=${lo}&max_power=${hi}&width_mm=${encodeURIComponent(width.value)}`);
        if (mine === seq) show(info);
      } catch (e) { error.textContent = e.message; error.hidden = false; }
    }
    width.addEventListener('change', rerender);
    const el = h('section', {class: 'card stack'}, h('h3', {}, 'Картинка на этой шкале'),
      h('p', {class: 'muted small'}, 'Серая картинка гравируется как есть. Цветная — либо как LightBurn переводит её в серый (по яркости), либо с подбором: для каждого пикселя берётся серый, '
        + 'который на этой шкале даёт ближайший цвет.'),
      h('div', {class: 'grid g3'}, field('Картинка', App.filePick(fileIn, 'Выбрать картинку')), field('Ширина на титане, мм', width),
        h('label', {class: 'row'}, byColour, h('span', {}, 'Цветная картинка: подобрать серые под её цвета'))),
      error, h('div', {class: 'toolbar'}, btn('Показать на титане', send, 'primary')), out);
    return {el, rerender};
  }

  /** Выбранная шкала: Min и Max, полоса и таблица «серый → цвет», подтверждение экспериментами, заливки, точки и картинка. */
  function scaleDetail(sc) {
    const span = sc.span;
    const slider = (label, initial) => {
      const range = h('input', {type: 'range', min: 0, max: 100, step: 0.1, value: initial, 'aria-label': label});
      const exact = h('input', {type: 'number', min: 0, max: 100, step: 'any', value: initial, 'aria-label': label, style: 'width:6em'});
      range.addEventListener('input', () => { exact.value = range.value; schedule(); });
      exact.addEventListener('change', () => { range.value = exact.value; schedule(); });
      return {exact, box: h('label', {class: 'f'}, h('span', {}, label), h('span', {class: 'row'}, range, exact))};
    };
    // the measured span rounded inwards to 0.1 %, so that white and black both stay inside it
    const low = slider('Min мощность, % (белый)', Math.ceil(span[0] * 10 - 1e-9) / 10), high = slider('Max мощность, % (чёрный)', Math.floor(span[1] * 10 + 1e-9) / 10);
    const powers = () => [+low.exact.value, +high.exact.value];
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const body = h('div', {class: 'stack'}, h('p', {class: 'muted'}, 'Загружаем шкалу…'));
    const picture = pictureBlock(sc, powers);
    let timer = null, seq = 0;
    async function load() {
      const [lo, hi] = powers();
      error.hidden = true;
      if (!(lo <= hi)) { error.textContent = 'Min мощность должна быть не выше Max.'; error.hidden = false; return; }
      const mine = ++seq;
      try {
        const d = await get(`/grey-scales/scale?${modeQuery(sc.mode)}&min_power=${lo}&max_power=${hi}`);
        if (mine !== seq) return;
        const levels = d.greys.levels;
        const unmeasured = 256 - d.greys.measured_levels;
        fill(body,
          h('h4', {}, 'Какой серый каким цветом выходит'),
          greyBar(levels),
          unmeasured ? h('p', {class: 'small muted'}, `Серых вне измеренных мощностей (${value(span[0], 1)}–${value(span[1], 1)} %): ${unmeasured} из 256 — заштрихованы; цвет там не прогнозируется.`) : null,
          greyTable(levels), confirmationBlock(d.confirmation), fillsBlock(d.fill_points), pointsBlock(d.curve),
          h('ul', {class: 'small'}, d.notes.map((n) => h('li', {}, I18N.tr(n)))));
      } catch (e) { error.textContent = e.message; error.hidden = false; }
      picture.rerender();
    }
    function schedule() { clearTimeout(timer); timer = setTimeout(load, 250); }
    load();
    return h('div', {class: 'stack'},
      h('section', {class: 'card stack'}, h('h3', {}, 'Шкала: ', settingsText(sc.mode, sc.dpi)),
        h('p', {class: 'muted small'}, `${materialLabel(sc.material)}. Измерено от ${value(span[0], 1)} до ${value(span[1], 1)} %. Серый картинки становится мощностью линейно: `
          + 'белый (255) — Min, чёрный (0) — Max; цвет между измеренными мощностями — линейно в Lab, за их пределами не прогнозируется.'),
        h('div', {class: 'grid g2'}, low.box, high.box), error, body),
      picture.el);
  }

  function kindsBlock() {
    const rows = Object.entries(PhotoModes.MODES).map(([key, m]) => [h('strong', {}, m.label), PhotoModes.FAMILY[m.family], m.settings,
      key === 'grayscale' ? 'здесь: по шкалам «серый → цвет»' : m.predict === 'profile' ? link('/photo-preview', 'прогноз по файлу LightBurn') : h('span', {class: 'muted'}, PhotoModes.PREDICT[m.predict])]);
    return h('details', {class: 'card'}, h('summary', {}, 'Виды фотогравировки LightBurn и что здесь предсказывается'),
      table(['Режим', 'Что задаёт серый', 'Что важно в настройках', 'Прогноз'], rows, '', true),
      h('p', {class: 'small muted'}, 'Шаг строк: в градациях серого он один на всю картинку (dpi = 25,4 / шаг). Слишком частые строки, как у цветных заливок, перегревают металл, '
        + 'и серый перестаёт давать разные цвета; пластина «Шкалы серого» по умолчанию сравнивает 2000, 1500, 1200 и 1000 dpi (0,0127–0,0254 мм).'));
  }

  App.register({id: 'photo-engraving', async render(ctx) {
    const [{scales}, devices, materials] = await Promise.all([get('/grey-scales'), get('/devices'), get('/materials')]);
    const plate = btn('Пластина «Шкалы серого»', () => PlateDialog.open(devices, materials, null, {type: 'grey_scales'}), 'btn-small', !devices.some((d) => d.lens));
    const list = h('div', {class: 'ge-scales'});
    const detail = h('div', {class: 'stack'});
    const wanted = ctx.query.scale;
    const key = (sc) => modeQuery(sc.mode);
    const choose = (sc) => {
      fill(list, scales.map((item) => scaleCard(item, item === sc, () => choose(item))));
      fill(detail, scaleDetail(sc));
    };
    if (scales.length) choose(scales.find((sc) => key(sc) === wanted) || scales[0]);
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Фотогравировка'),
        h('p', {class: 'sub'}, 'Режим градаций серого: все настройки постоянны, кроме мощности. Серый картинки задаёт мощность от Min до Max, а мощность на титане даёт цвет — '
          + 'поэтому одна серая картинка выходит несколькими цветами. Шкала показывает, какой серый каким цветом выходит при ваших настройках, по вашим измерениям.')),
        h('span', {class: 'spacer'}), plate, link('/photo-preview', 'Прогноз по файлу LightBurn'), link('/photo', 'Непрерывная полосами')),
      scales.length ? h('section', {class: 'stack'}, h('h3', {}, `Измеренные шкалы (${scales.length})`), list)
        : h('div', {class: 'card empty'}, h('h3', {}, 'Шкал пока нет'),
          h('p', {}, 'Шкала появляется, когда принята фотография гравировки в режиме градаций серого: пластины «Шкалы серого» или вашей фотогравировки (слой-изображение в файле LightBurn).')),
      detail, kindsBlock());
  }});
})();
