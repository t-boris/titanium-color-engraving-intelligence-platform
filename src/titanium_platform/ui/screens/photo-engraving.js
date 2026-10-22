/* Фотогравировка (REQ-059, REQ-061): работы на измеренных шкалах. Шкала — постоянные настройки (лазер, линза, титан, скорость,
   частота, импульс, шаг строк, проходы) с измеренной кривой «мощность → цвет»; в градациях серого серый картинки задаёт мощность от Min
   (белый) до Max (чёрный), и на титане мощность даёт цвет. Вид гравировки (0.21.0): «Новая работа» вторым шагом спрашивает «Какая гравировка?»
   и показывает картинку в каждом виде; в видах точками каждая точка бьёт на одной мощности — цвет шкалы при ней, между точками очищенный
   титан; пока такой вид не гравировался, это оценка по шкале. Раскраска по объектам (0.21.0), как в раскраске: губам, очкам, волосам,
   кускам фона — каждому свой основной цвет шкалы (щелчком по цвету, темой, «Случайно» или по просьбе AI), светлое и тёмное объекта
   ложатся вокруг этого цвета в его семействе.
   Работа — картинка на шкале, как векторная работа (DEC-104): список «Мои работы» (открыть, сделать копию, переименовать, удалить),
   «Новая работа» в два шага (картинка, название, ширина; затем «Какая гравировка?»), сама работа на один экран: шкалы слева, картинка рядом с прогнозом посередине, справа
   вкладки; шкала, Min и Max, ширина и подбор серых сохраняются в работе сразу. Страница «Шкалы серого» показывает, какой серый каким
   цветом выходит на каждой шкале и подтверждают ли это эксперименты.
   Цвет зависит от размера гравировки (DEC-107): от длины строки, у картинки — её ширины. Шкала показывает, при какой ширине она измерена;
   работа берёт цвета при своей ширине — измеренные, между двумя измеренными или ближайшие, и говорит какие.
   Адреса: #/photo-engraving — мои работы; ?work=<id> — работа; ?scales=1 (или ?scale=<режим>) — шкалы серого. Другие виды —
   #/photo-preview (прогноз по файлу LightBurn) и #/photo (непрерывная полосами). */
'use strict';
(() => {
  const {h, fill, btn, link, pill, get, post, del, form, field, go, toast, modal, confirmBox, labText, duration, table, fail} = App;
  let keys = null;                                     // клавиши открытой работы (Ctrl+Z, Ctrl+Shift+Z), как в редакторе векторной работы
  document.addEventListener('keydown', (ev) => { if (keys) keys(ev); });
  const PICTURES = 'image/png,image/jpeg,image/tiff,image/bmp,image/webp';
  const SPREAD_LIMIT = 5;                       // ΔE within which independent engravings agree (agreement.AGREEMENT_DE, DEC-083)
  const BAR_SEGMENTS = 64;                      // segments of the grey -> colour bar (4 grey levels each)
  const TABLE_STEP = 17;                        // the 16 greys of the table: 255, 238, ... 0, the steps of the plate's ramp
  const value = (v, d = 2) => (v == null ? '—' : String(+(+v).toFixed(d)).replace('.', ','));
  const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);
  const materialLabel = (m) => (m ? [m.name, m.grade, m.thickness_mm != null ? `${m.thickness_mm} мм` : null, m.batch].filter(Boolean).join(' · ') : 'титан не указан');
  /** Титан шкалы (DEC-110): все пластины одной марки — один титан, какого бы размера, толщины и партии ни были; запись без марки — сама по себе. */
  const titaniumLabel = (sc) => {
    const m = sc.material;
    if (!m || !m.grade) return materialLabel(m);
    const on = ((sc.titanium || {}).measured_on || []).map((t) => t.name);
    return `${m.family && m.family.toLowerCase() !== 'titanium' ? m.family : 'Титан'} ${m.grade}` + (on.length ? ` · измерена на ${on.join(', ')}` : '');
  };
  /** Шкала работы: те же лазер, линза и настройки и та же пластина или другая пластина того же титана. */
  const sameScale = (sc, m) => modeQuery({...sc.mode, material_id: null}) === modeQuery({...m, material_id: null})
    && (sc.mode.material_id === m.material_id || ((sc.titanium || {}).records || []).includes(m.material_id));
  const HOW = {'grey ramp': 'пластина шкал серого', 'tonal profile': 'фотогравировка'};
  const REFERENCE = {chart: ['цвета по эталонной карте', 'ok'], 'clean titanium': ['цвета относительно камеры, приведены к чистому титану', 'warn'],
    'as photographed': ['цвета относительно камеры, как сняты', 'warn']};

  const settingsText = (m, dpi) => `${value(m.speed, 1)} мм/с · ${value(m.frequency, 1)} кГц · ${m.pulse_width == null ? 'импульс не указан' : value(m.pulse_width, 0) + ' нс'}`
    + ` · шаг ${value(m.line_interval, 4)} мм${dpi ? ` (${dpi} dpi)` : ''} · проходов ${m.passes ?? 1}${m.global_passes > 1 ? ` · глобально ${m.global_passes}×` : ''}`;
  const modeQuery = (m) => new URLSearchParams(Object.entries({device_id: m.device_id, lens_id: App.lensParam(m.lens_id), material_id: m.material_id,
    speed: m.speed, frequency: m.frequency, pulse_width: m.pulse_width, line_interval: m.line_interval, passes: m.passes ?? 1, global_passes: m.global_passes ?? 1})
    .filter(([, v]) => v != null)).toString();
  const GRAYSCALE = 'grayscale';
  const dotted = (v) => !!v.kind && v.kind !== GRAYSCALE;                                    // a dot kind: every dot at one power
  const kindName = (key) => { const t = PhotoModes.label(key); return t.charAt(0).toUpperCase() + t.slice(1); };
  const greyChip = (level) => h('span', {class: 'sw', style: `background:rgb(${level},${level},${level})`});
  const hexChip = (hex) => (hex ? h('span', {class: 'sw', style: `background:${hex}`}) : h('span', {class: 'sw ge-none', title: 'не измерено'}));

  function confirmationPill(c) {
    if (!c || c.median_de == null) return pill(c && c.engravings > 1 ? 'гравировки не пересекаются по мощности' : 'одна гравировка: подтвердить нечем', 'warn');
    return pill(`${c.confirmed ? 'подтверждена' : 'не подтверждена'}: медиана ${value(c.median_de, 1)} ΔE`, c.confirmed ? 'ok' : 'warn');
  }

  const mm = (v) => `${value(v, 1)} мм`;
  const mmList = (list) => list.map((v) => value(v, 1)).join(' и ') + ' мм';

  /** Как цвета шкалы относятся к ширине (``size`` прогноза, DEC-107): короткая плашка и строка пояснения. */
  function sizeText(size) {
    if (!size) return null;
    if (size.how === 'measured') return {short: `шкала измерена при ширине ${mm(size.from_mm[0])}`, tone: 'ok',
      long: `Цвета измерены при ширине ${mm(size.from_mm[0])}${size.measured_mm.length > 1 ? ` (шкала измерена при ${mmList(size.measured_mm)})` : ''}.`};
    if (size.how === 'between') return {short: `${mm(size.row_mm)}: между измерениями ${mmList(size.from_mm)}`, tone: 'warn',
      long: `При ширине ${mm(size.row_mm)} шкала не измерялась: цвета взяты между измерениями при ${mmList(size.from_mm)}. Чтобы проверить, выгравируйте пробу этой ширины.`};
    if (size.how === 'outside') return {short: `${mm(size.row_mm)}: шкала измерена при ${mmList(size.measured_mm)}`, tone: 'warn',
      long: `Шкала измерена при ширине ${mmList(size.measured_mm)}, при ${mm(size.row_mm)} — нет: цвета взяты при ${mm(size.from_mm[0])} и на этой ширине могут выйти другими.`};
    return {short: 'ширина измерений неизвестна', tone: 'warn', long: 'Неизвестно, при какой ширине измерена шкала: её файлы LightBurn недоступны.'};
  }
  const SIZE_ABOUT = 'Цвет на титане зависит от длины строки гравировки (у картинки — от её ширины): лазер возвращается к точке через строку, '
    + 'и на коротких строках титан не успевает остыть.';

  /** Карточка шкалы в списке: цвета по измеренным мощностям, настройки, чем измерена, подтверждение и время на см². */
  function scaleCard(sc, chosen, choose) {
    const bar = sc.bar.length ? `linear-gradient(to right, ${sc.bar.map((b) => b.hex).join(', ')})` : 'none';
    const kinds = Object.entries(sc.by_kind).map(([how, n]) => `${HOW[how] || how}: ${n}`).join(' · ');
    return h('button', {type: 'button', class: 'ge-scale' + (chosen ? ' is-chosen' : ''), 'aria-pressed': String(chosen), onClick: choose},
      h('span', {class: 'ge-bar', style: `background:${bar}`}),
      h('span', {class: 'ge-ends small'}, h('span', {}, `P ${value(sc.span[0], 1)} %`), h('span', {}, `P ${value(sc.span[1], 1)} %`)),
      h('strong', {}, settingsText(sc.mode, sc.dpi)),
      h('span', {class: 'small muted'}, `${titaniumLabel(sc)} · ${kinds} · ${value(sc.time_s_per_cm2, 0)} с/см²`),
      sc.sizes && sc.sizes.length ? h('span', {class: 'small muted'}, `измерена при ширине ${mmList(sc.sizes.map((z) => z.row_mm))}`) : null,
      h('span', {class: 'row'}, confirmationPill(sc.confirmation), pill(...(REFERENCE[sc.reference] || [sc.reference]))));
  }

  /** Полоса «серый → цвет» при выбранных Min и Max: слева белый (Min), справа чёрный (Max), как ступени пластины; вне измеренного — штриховка.
      С ``dot`` ({power, pick}) — полоса цветов по мощностям шкалы для вида точками: метка на мощности точек, щелчок выбирает другую. */
  function greyBar(levels, dot = null) {
    const at = (i) => levels[255 - Math.round(i * 255 / (BAR_SEGMENTS - 1))];
    const segments = Array.from({length: BAR_SEGMENTS}, (_, i) => at(i));
    const lo = levels[255].power, hi = levels[0].power;
    const strip = h('div', {class: 'ge-strip' + (dot ? ' ge-pickable' : ''), 'aria-label': dot ? 'Цвет точек при каждой мощности: щёлкните, чтобы выбрать' : 'Цвет каждого серого'},
      segments.map((row) => h('span', {class: row.hex ? '' : 'ge-none', style: row.hex ? `background:${row.hex}` : '',
        title: dot ? `мощность ${value(row.power)} %${row.hex ? '' : ' · не измерено'}` : `серый ${row.level} · мощность ${value(row.power)} %${row.hex ? '' : ' · не измерено'}`})));
    if (!dot) {
      return h('div', {class: 'stack ge-greybar'}, strip, h('div', {class: 'ge-strip ge-ramp', 'aria-hidden': 'true'}),
        h('div', {class: 'ge-ends small'}, h('span', {}, `белый 255 · Min ${value(lo, 1)} %`), h('span', {}, `чёрный 0 · Max ${value(hi, 1)} %`)));
    }
    strip.addEventListener('click', (ev) => {
      const box = strip.getBoundingClientRect();
      if (!(box.width > 0)) return;
      const share = Math.min(1, Math.max(0, (ev.clientX - box.left) / box.width));
      dot.pick(Math.round((lo + share * (hi - lo)) * 10) / 10);
    });
    const mark = h('span', {class: 'ge-dotmark', 'aria-hidden': 'true', style: `left:${hi > lo ? Math.min(100, Math.max(0, (dot.power - lo) / (hi - lo) * 100)) : 0}%`});
    return h('div', {class: 'stack ge-greybar'}, h('div', {class: 'ge-markbox'}, strip, mark),
      h('div', {class: 'ge-ends small'}, h('span', {}, `${value(lo, 1)} %`), h('span', {}, `точки: ${value(dot.power, 1)} %`), h('span', {}, `${value(hi, 1)} %`)));
  }

  // L, a and b each stay whole: a narrow column breaks the colour only between them
  const labLines = (lab) => labText(lab).replace(/ (?!·)(?<!· )/g, '\u00a0');

  function greyTable(levels) {
    const rows = [];
    for (let level = 255; level >= 0; level -= TABLE_STEP) {
      const r = levels[level];
      rows.push([h('span', {class: 'ge-nowrap'}, greyChip(level), ` ${level}`), value(r.power), r.lab ? h('span', {class: 'ge-lab'}, hexChip(r.hex), ' ', labLines(r.lab)) : h('span', {class: 'muted'}, 'вне измеренных мощностей'),
        r.spread_de == null ? h('span', {class: 'muted'}, '—') : pill(`${value(r.spread_de, 1)} ΔE`, r.spread_de > SPREAD_LIMIT ? 'warn' : 'ok')]);
    }
    return table(['Серый картинки (0–255)', 'Мощность, %', 'Цвет на титане', 'Расхождение гравировок'], rows, '', true);
  }

  const sourceText = (s) => [s.title, HOW[s.how] || s.how, s.layer_name, s.photo ? `фото ${s.photo}` : null].filter(Boolean).join(' · ');

  /** Каждая гравировка шкалы — строкой списка: в узкой панели справа таблица из шести колонок не помещается. */
  function confirmationBlock(c) {
    const rows = c.rows.map((r) => h('li', {class: 'ge-entry'},
      h('div', {class: 'ge-entry-head'}, h('span', {}, link('/experiment/' + encodeURIComponent(r.engraving.experiment), r.engraving.title), ` · ${HOW[r.engraving.how] || r.engraving.how}`),
        r.median_de == null ? null : pill(`медиана ${value(r.median_de, 1)} ΔE`, r.median_de > c.tolerance_de ? 'warn' : 'ok')),
      h('div', {class: 'small muted'}, [`точек ${r.points}`, r.compared ? `сравнено ${r.compared}` : 'нечем сравнить',
        r.max_de == null ? null : `максимум ${value(r.max_de, 1)} ΔE`, r.within == null ? null : `в пределах ${c.tolerance_de} ΔE: ${value(r.within * 100, 0)} %`].filter(Boolean).join(' · '))));
    return h('div', {class: 'stack'}, h('h4', {}, 'Подтверждают ли эксперименты'),
      h('p', {class: 'small'}, 'Каждая гравировка сравнивается со шкалой, построенной по всем остальным: на её мощностях — разница цвета. Подтверждена, если медиана не больше '
        + `${c.tolerance_de} ΔE. `, confirmationPill(c)),
      rows.length ? h('ul', {class: 'ge-entries'}, rows) : h('p', {class: 'muted'}, 'Нет гравировок'));
  }

  function fillsBlock(fills) {
    if (!fills.length) return null;
    return h('details', {}, h('summary', {}, `Заливки с теми же настройками (${fills.length}) — для сравнения, в шкалу не входят`),
      h('p', {class: 'small muted'}, 'Заливка и серый картинки на той же мощности выходят разным цветом (на ваших данных — до 36 ΔE в светлой и средней части), поэтому шкала строится только по фотогравировкам и пластинам шкал серого.'),
      table(['Мощность, %', 'Цвет заливки', 'Разница со шкалой', 'Где'], fills.map((f) => [value(f.power), h('span', {class: 'ge-lab'}, hexChip(f.hex), ' ', labLines(f.lab)),
        f.de == null ? h('span', {class: 'muted'}, f.curve_lab ? 'другой способ измерения' : 'вне шкалы') : pill(`${value(f.de, 1)} ΔE`, f.de > SPREAD_LIMIT ? 'warn' : 'ok'),
        sourceText(f.source)]), '', true));
  }

  function pointsBlock(curve) {
    return h('details', {}, h('summary', {}, `Измеренные точки шкалы (${curve.points.length})`),
      table(['Мощность, %', 'Цвет', 'Гравировок', 'Где измерено'], curve.points.map((p) => [value(p.power), h('span', {class: 'ge-lab'}, hexChip(p.hex), ' ', labLines(p.lab)), String(p.engravings),
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

  const newSlots = () => ({title: h('span', {class: 'sub ge-settings'}), powers: h('div', {class: 'ge-powers'}), error: h('div'), bar: h('div', {class: 'ge-barbox'}),
    scale: h('div', {class: 'stack'}), confirm: h('div', {class: 'stack'}), points: h('div', {class: 'stack'})});

  /** Места шкалы без шкалы: одна строка ``text`` вместо Min и Max, полосы и вкладок. */
  function emptySlots(slots, text) {
    fill(slots.title);
    slots.title.setAttribute('title', '');
    fill(slots.powers);
    fill(slots.error);
    for (const place of [slots.bar, slots.scale, slots.confirm, slots.points]) fill(place, h('p', {class: 'muted'}, text));
  }

  /** Шкала: её настройки, Min и Max, полоса «серый → цвет» и во вкладках таблица серых, подтверждение экспериментами, заливки и точки.
      ``slots`` — места экрана, которые она заполняет. ``initial`` — Min и Max (у работы — её), иначе измеренный диапазон, округлённый внутрь
      до 0,1 %, чтобы белый и чёрный оба остались в нём; ``changed(lo, hi)`` узнаёт новые Min и Max, когда их поменяли. ``rowMm`` — ширина,
      при которой показывать цвета (у работы — её ширина); без неё — ширина, измеренная больше всего, и кнопки других измеренных ширин.
      ``stop()`` — шкала больше не показывается: её отложенное изменение и поздние ответы не применяются. ``dot`` ({power, changed(p)}) —
      работа в виде точками: вместо Min и Max одна мощность точек, полоса — цвета по всем измеренным мощностям, щелчок по ней выбирает мощность. */
  function scaleDetail(sc, slots, {initial = null, changed = null, rowMm = null, dot = null} = {}) {
    let span = sc.span;
    let timer = null, seq = 0, stopped = false;
    let atMm = rowMm != null ? rowMm : (sc.size ? sc.size.row_mm : null);
    const widths = rowMm == null && sc.sizes && sc.sizes.length > 1 ? h('div', {class: 'row ge-sizes', role: 'group', 'aria-label': 'Ширина, при которой показать цвета'},
      h('span', {class: 'small'}, 'Ширина:'), sc.sizes.map((z) => h('button', {type: 'button', class: 'btn btn-small', 'aria-pressed': String(z.row_mm === atMm),
        title: `измерено гравировок: ${z.engravings}, точек: ${z.points}`, onClick: (ev) => {
          const self = ev.currentTarget;
          atMm = z.row_mm;
          for (const b of self.parentNode.querySelectorAll('button')) b.setAttribute('aria-pressed', String(b === self));
          load(false);
        }}, mm(z.row_mm)))) : null;
    const slider = (label, short, start, moved = () => schedule()) => {
      const range = h('input', {type: 'range', min: 0, max: 100, step: 0.1, value: start, 'aria-label': label});
      const exact = h('input', {type: 'number', min: 0, max: 100, step: 'any', value: start, 'aria-label': label});
      range.addEventListener('input', () => { exact.value = range.value; moved(); });
      exact.addEventListener('change', () => { range.value = exact.value; moved(); });
      return {exact, range, box: h('label', {class: 'ge-power', title: label}, h('span', {class: 'small'}, short), range, exact)};
    };
    const measured = [Math.ceil(span[0] * 10 - 1e-9) / 10, Math.floor(span[1] * 10 + 1e-9) / 10];
    const [lo0, hi0] = dot ? measured : initial || measured;
    const low = slider('Min мощность, % (белый)', 'Min, %', lo0);
    const high = slider('Max мощность, % (чёрный)', 'Max, %', hi0);
    let levelsShown = null;
    const dotPower = dot ? slider('Мощность точек, %', 'Точки, %', dot.power, () => { clearTimeout(timer); timer = setTimeout(() => pickDot(+dotPower.exact.value), 250); }) : null;
    /** Мощность точек ``p``: метка на полосе сразу, работа узнаёт её (сервер проверит, что шкала там измерена). */
    function pickDot(p) {
      if (!(p >= 0 && p <= 100)) return;
      dotPower.exact.value = String(p);
      dotPower.range.value = String(p);
      dot.power = p;
      if (levelsShown) fill(slots.bar, greyBar(levelsShown, {power: p, pick: pickDot}));
      dot.changed(p);
    }
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const loading = () => h('p', {class: 'muted'}, 'Загружаем шкалу…');
    fill(slots.title, settingsText(sc.mode, sc.dpi));
    slots.title.setAttribute('title', `${settingsText(sc.mode, sc.dpi)} · ${titaniumLabel(sc)}`);
    fill(slots.powers, ...(dot ? [dotPower.box] : [low.box, high.box]), widths);
    fill(slots.error, error);
    fill(slots.bar, loading());
    for (const tab of [slots.scale, slots.confirm, slots.points]) fill(tab, loading());
    async function load(byOperator) {
      const lo = +low.exact.value, hi = +high.exact.value;
      error.hidden = true;
      if (!(lo <= hi)) { error.textContent = 'Min мощность должна быть не выше Max.'; error.hidden = false; return; }
      if (byOperator && changed) changed(lo, hi);
      const mine = ++seq;
      try {
        const d = await get(`/grey-scales/scale?${modeQuery(sc.mode)}&min_power=${lo}&max_power=${hi}${atMm != null ? `&row_mm=${atMm}` : ''}`);
        if (stopped || mine !== seq) return;
        span = d.span;
        const size = sizeText(d.size);
        const levels = d.greys.levels;
        const unmeasured = 256 - d.greys.measured_levels;
        levelsShown = levels;
        fill(slots.bar, greyBar(levels, dot ? {power: dot.power, pick: pickDot} : null));
        fill(slots.scale,
          h('p', {class: 'small muted'}, `${titaniumLabel(sc)}. Измерено от ${value(span[0], 1)} до ${value(span[1], 1)} %. Серый картинки становится мощностью линейно: `
            + 'белый (255) — Min, чёрный (0) — Max; цвет между измеренными мощностями — линейно в Lab, за их пределами не прогнозируется.'),
          unmeasured ? h('p', {class: 'small muted'}, `Серых вне измеренных мощностей (${value(span[0], 1)}–${value(span[1], 1)} %): ${unmeasured} из 256 — заштрихованы; цвет там не прогнозируется.`) : null,
          size ? h('p', {class: 'small'}, pill(size.short, size.tone), ' ', size.long, h('span', {class: 'muted'}, ' ' + SIZE_ABOUT)) : null,
          greyTable(levels), h('ul', {class: 'small'}, d.notes.map((n) => h('li', {}, I18N.tr(n)))));
        fill(slots.confirm, confirmationBlock(d.confirmation));
        fill(slots.points, fillsBlock(d.fill_points), pointsBlock(d.curve));
      } catch (e) { if (!stopped && mine === seq) { error.textContent = e.message; error.hidden = false; } }
    }
    function schedule() { clearTimeout(timer); timer = setTimeout(() => load(true), 250); }
    load(false);
    return {stop() { stopped = true; clearTimeout(timer); }};
  }

  // ---- работа ------------------------------------------------------------------------------------------------------------------------

  /** «Проба на ширине работы» (DEC-107): пластина с одной полоской серого шириной с работу на настройках её шкалы, Min и Max. Её фото
      измеряет шкалу при ширине работы до того, как гравируется картинка; кнопка открывает созданный эксперимент. Главная кнопка, пока
      при этой ширине шкала не измерена. */
  function rampOffer(view, size) {
    const dots = dotted(view);
    const make = btn(dots ? 'Проба этого вида' : 'Проба на ширине работы', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/photo-works/${view.id}/width-ramp`, {}); toast(`Создано: ${made.name}`, 'ok'); go('/experiment/plan-' + made.plan_id); }
      catch (e) { fail(e); self.disabled = false; }
    }, (dots ? view.picture && !view.picture.estimate : size && size.how === 'measured') ? 'btn-small' : 'primary btn-small');
    if (dots) {
      return h('p', {class: 'small'}, make, h('span', {class: 'muted'}, ` Пластина с одной полоской серого ${mm(view.width_mm)} в ширину в виде «${kindName(view.kind)}» `
        + `на мощности точек ${value(view.dot_power, 1)} % и настройках шкалы: выгравируйте её, сфотографируйте и загрузите — вид будет измерен на ваших настройках, `
        + 'и картинка покажется по измеренным тонам вместо оценки.'));
    }
    return h('p', {class: 'small'}, make, h('span', {class: 'muted'}, ` Пластина с одной полоской серого ${mm(view.width_mm)} в ширину на настройках шкалы, `
      + `Min ${value(view.min_power, 1)} % и Max ${value(view.max_power, 1)} %: выгравируйте её, сфотографируйте и загрузите — шкала будет измерена при ширине работы.`));
  }

  const CHOICES = [['drawing', 'Сохранить рисунок'], ['nearest', 'Ближайший цвет'], ['objects', 'Раскраска по объектам']];
  const CHOICE_ABOUT = '«Сохранить рисунок»: тона картинки раскладываются по одной плавной полосе шкалы — от самого светлого её цвета к самому тёмному, '
    + 'светлота только убывает, оттенок не скачет; соседние тона получают соседние мощности, поэтому кожа остаётся ровной, с градиентом, без пятен. '
    + 'Зерно и квадраты JPEG сглаживаются (до 0,25 мм), губы, глаза и тени лица (до 1,5 мм) подчёркиваются, средние тона светлеют. Оттенки картинки '
    + 'не повторяются — вся картинка в цветах этой полосы. «Ближайший цвет»: серый, который на шкале даёт ближайший цвет, даже если он намного '
    + 'темнее или светлее. «Раскраска по объектам»: как «Сохранить рисунок», но объекты, которым во вкладке «Раскраска» дан свой цвет, — в нём.';
  const CONTOURS_ABOUT = 'только при подборе серых под цвета: где граница картинки (губы, глаза, блики) на титане потерялась бы, она обводится '
    + 'линией 0,3 мм — самым тёмным серым шкалы, на тёмном или у светлого блика — самым светлым. Внутри части с правилом «Один тон» не обводится.';

  /** Что сказать о подборе серых (``colour_match`` с сервера): насколько сохранён рисунок или насколько близки цвета. */
  function matchText(match) {
    if (!match) return null;
    const used = `использовано серых ${match.greys_used} из ${match.greys_available}`;
    if (match.choice === 'objects') {
      const done = match.objects || [];
      return h('p', {}, h('strong', {}, 'Раскраска по объектам: '), done.length
        ? h('span', {}, `в своих цветах ${done.length} ${done.length === 1 ? 'объект' : done.length < 5 ? 'объекта' : 'объектов'} — `,
          ...done.flatMap((o, i) => [i ? ', ' : '', hexChip(o.hex), objectName(o.key)]),
          `; остальное — как «Сохранить рисунок». Порядок светлого и тёмного совпадает с картинкой${match.order == null ? '' : ` на ${value(match.order * 100, 0)} %`}; ${used}.`)
        : 'ни одному объекту цвет ещё не дан — вся картинка как при «Сохранить рисунок». Цвета объектов — во вкладке «Раскраска».');
    }
    if (match.choice === 'nearest') {
      return h('p', {}, h('strong', {}, 'Подбор по цвету: '), `ближайшие цвета шкалы отличаются от цветов картинки в среднем на ${value(match.median_de, 1)} ΔE `
        + `(у 90 % пикселей — не больше ${value(match.p90_de, 1)}); ${used}.`);
    }
    return h('p', {}, h('strong', {}, 'Рисунок сохранён: '), `тона картинки разложены по плавной полосе шкалы из ${match.path} серых `
      + `(L* от ${value(match.reach[1], 0)} до ${value(match.reach[0], 0)})${match.order == null ? '' : `, порядок светлого и тёмного совпадает с картинкой `
      + `на ${value(match.order * 100, 0)} %`}; оттенки картинки не повторяются (в среднем ${value(match.median_de, 1)} ΔE от её цветов); ${used}.`);
  }

  /** Что сказать о контурах работы: выключены, обводить нечего или какую долю картинки занимают линии. */
  function contoursText(view, info) {
    if (!view.by_colour) return null;
    if (!view.contours) return h('p', {class: 'small muted'}, 'Контуры выключены: границы, которые на титане теряются, не обводятся.');
    const share = info.contours_report ? info.contours_report.share : 0;
    return h('p', {class: 'small'}, h('strong', {}, 'Контуры: '), share > 0
      ? `границы, которые на титане потерялись бы, обведены линией 0,3 мм — ${value(share * 100, share < 0.001 ? 2 : 1)} % картинки.`
      : 'на титане не теряется ни одна граница картинки — обводить нечего.');
  }

  /** Картинка работы на её шкале: ширина, подбор серых и контуры над картинкой, картинка рядом с прогнозом посередине, время под ней,
      подробности — во вкладке «Картинка». Прогноз приходит с сервера готовым (``show(view, sc)``); всё это сохраняется в работе через
      ``save`` (DEC-108). */
  function workPicture(save, chooseKind) {
    const kind = btn('Вид: градации серого', () => chooseKind(), 'btn-small');
    kind.setAttribute('title', 'Какая гравировка: градации серого или один из видов точками — с картинкой в каждом');
    const width = h('input', {type: 'number', min: '1', max: '1000', step: 'any', 'aria-label': 'Ширина на титане, мм', style: 'width:6em'});
    const byColour = h('input', {type: 'checkbox'});
    const choice = h('select', {'aria-label': 'Как подбирать серые', title: CHOICE_ABOUT}, CHOICES.map(([v, t]) => h('option', {value: v}, t)));
    const contours = h('input', {type: 'checkbox', 'aria-label': 'Контуры'});
    const out = h('div', {class: 'ge-stage'});
    const foot = h('div', {class: 'ge-foot'});
    const details = h('div', {class: 'stack'});
    width.addEventListener('change', () => save({width_mm: +width.value}));
    byColour.addEventListener('change', () => save({by_colour: byColour.checked}));
    choice.addEventListener('change', () => save({colour_choice: choice.value}));
    contours.addEventListener('change', () => save({contours: contours.checked}));
    const waiting = () => fill(out, h('p', {class: 'muted ge-placeholder'}, 'Считаем прогноз…'));
    function show(view, sc) {
      const dots = dotted(view);
      fill(kind, `Вид: ${kindName(view.kind || GRAYSCALE)}`);
      width.value = String(view.width_mm);
      byColour.checked = !!view.by_colour;
      byColour.disabled = dots;
      choice.value = view.colour_choice || 'drawing';
      choice.disabled = dots || !view.by_colour;
      contours.checked = !!view.contours;
      contours.disabled = dots || !view.by_colour;
      const info = view.picture;
      if (!info) {
        fill(out, h('div', {class: 'ge-placeholder stack'}, h('p', {class: 'alert warn'}, I18N.tr(view.problem)),
          h('p', {class: 'muted'}, 'Выберите измеренную шкалу слева: картинка останется, Min и Max станут измеренным диапазоном шкалы.')));
        fill(foot);
        fill(details, h('p', {class: 'muted'}, 'Прогноза нет: шкала этой работы не измерена.'));
        return;
      }
      if (dots) { showDots(view, info, sc); return; }
      const t = info.time;
      const cleaning = t.layers.length > 1 ? t.layers[0] : null;      // the file cleans the titanium first (C00)
      const size = `${value(info.size_mm.width, 1)} × ${value(info.size_mm.height, 1)} мм`;
      const lined = info.contours_report && info.contours_report.share > 0 ? ' и контуры' : '';
      fill(out,
        h('div', {class: 'pp-captions'}, h('span', {}, (info.by_colour ? 'Подобранные серые' : 'Картинка (как её видит LightBurn)') + lined), h('span', {}, 'Прогноз на титане')),
        h('div', {class: 'pp-stage'}, h('img', {class: 'pp-image', src: info.preview, alt: 'Картинка и её прогноз на титане'})));
      const atSize = sizeText(info.scale_size);
      fill(foot,
        h('span', {}, h('strong', {}, `Время гравировки: ≈ ${duration(t.seconds)}`), ` для ${size}`),
        atSize ? h('span', {title: atSize.long}, pill(atSize.short, atSize.tone)) : null,
        info.outside_share > 0 ? pill(`${value(info.outside_share * 100, 1)} % вне шкалы`, 'warn') : null);
      fill(details,
        h('p', {}, h('strong', {}, `Время гравировки: ≈ ${duration(t.seconds)}`), ` для ${size}${sc ? ` на шкале ${value(sc.time_s_per_cm2, 0)} с/см²` : ''}`
          + (cleaning ? `, из них чистка ≈ ${duration(cleaning.seconds)}` : ''),
          h('span', {class: 'muted small'}, ' — оценка: сначала чистка по прямоугольнику картинки, затем строки на всю ширину картинки (в градациях серого бьёт и белый — на Min), скорость, шаг строк и проходы; разгон и переходы не учтены.')),
        info.outside_share > 0 ? h('p', {class: 'alert warn'}, `${value(info.outside_share * 100, 1)} % картинки требует мощности вне измеренной шкалы: там прогноза нет, места заштрихованы.`) : null,
        matchText(info.colour_match),
        contoursText(view, info),
        atSize ? h('p', {class: 'small'}, pill(atSize.short, atSize.tone), ' ', atSize.long, h('span', {class: 'muted'}, ' ' + SIZE_ABOUT)) : null,
        rampOffer(view, info.scale_size),
        h('p', {class: 'small'}, `Файл LightBurn: ${cleaning ? `C00 — чистка ${cleaning.name} по прямоугольнику картинки, первой (шкалы измерены на очищенных пластинах); C01 — ` : ''}`
          + `слой-изображение в режиме градаций серого: Min ${value(info.power_range[0], 1)} %, Max ${value(info.power_range[1], 1)} %, `
          + `${settingsText(view.scale, info.dpi)}. Картинка ${value(info.size_mm.width, 1)} мм в ширину, левый верхний угол в нуле.`),
        h('ul', {class: 'small'}, info.notes.map((n) => h('li', {}, I18N.tr(n)))),
        info.by_colour ? h('details', {}, h('summary', {class: 'small'}, 'Исходная цветная картинка'),
          h('img', {class: 'pp-image', src: `/api/photo-works/${view.id}/picture`, alt: 'Исходная картинка'})) : null,
        h('p', {class: 'muted small'}, 'Серая картинка гравируется как есть. Цветная — либо как LightBurn переводит её в серый (по яркости), либо с подбором серых под цвета. '
          + CHOICE_ABOUT + ' Контуры: ' + CONTOURS_ABOUT + ' Прогноз и файл LightBurn — одна и та же картинка; прогноз пересчитывается сам, когда меняются шкала, Min и Max, '
          + 'ширина, подбор или контуры.'));
    }
    /** Работа в виде точками: картинка рядом с точками на титане издалека (оценка по шкале), точки вблизи, мощность и файл. */
    function showDots(view, info, sc) {
      const t = info.time, d = info.dots, name = kindName(view.kind), measured = d.measured;
      const cleaning = t.layers.length > 1 ? t.layers[0] : null;
      const size = `${value(info.size_mm.width, 1)} × ${value(info.size_mm.height, 1)} мм`;
      const estimate = 'оценка по шкале: этот вид ещё не гравировался';
      fill(out,
        h('div', {class: 'pp-captions'}, h('span', {}, 'Картинка (как её видит LightBurn)'), h('span', {}, `${name} на титане — ${measured ? 'по измеренной пробе' : 'оценка'}`)),
        h('div', {class: 'pp-stage'}, h('img', {class: 'pp-image', src: info.preview, alt: `Картинка и она же в виде «${name}» на титане`})));
      const atSize = sizeText(info.scale_size);
      fill(foot,
        h('span', {}, h('strong', {}, `Время гравировки: ≈ ${duration(t.seconds)}`), ` для ${size}`),
        h('span', {class: 'row'}, 'точки ', hexChip(d.hex), ` ${value(d.power, 1)} % на титане `, hexChip(d.clean_hex)),
        measured ? pill(`измерено: ${measured.tones} тонов этого вида`, 'ok') : pill(estimate, 'warn'),
        atSize ? h('span', {title: atSize.long}, pill(atSize.short, atSize.tone)) : null);
      fill(details,
        measured ? h('p', {}, h('strong', {}, `${name}. `), `Каждая точка бьёт на ${value(d.power, 1)} %. Цвета картинки — как сфотографирована проба этого вида `
          + `на этих настройках и этом титане: ${measured.tones} тонов. Мощность точек меняется на полосе шкалы; при другой мощности снова будет оценка, пока её не измерить.`)
          : h('p', {}, h('strong', {}, `${name}. `), `Каждая точка бьёт на ${value(d.power, 1)} % — это цвет шкалы при этой мощности `, hexChip(d.hex),
            '; между точками — очищенный титан ', hexChip(d.clean_hex), `. Тон — сколько точек: они покрывают ${value(d.struck_share * 100, 0)} % картинки, `
            + 'издалека глаз смешивает их с титаном. Мощность точек меняется на полосе шкалы: щёлкните по цвету, который нужен точкам.'),
        measured ? h('ul', {class: 'small'}, measured.notes.map((n) => h('li', {}, I18N.tr(n))))
          : h('p', {class: 'alert warn small'}, 'Это оценка: этот вид на этих настройках ещё не гравировался. Цвет точки взят со шкалы, измеренной строками; '
            + 'точка — самая короткая строка, а цвет на титане зависит от длины строки, поэтому настоящие точки могут выйти другого оттенка. '
            + 'Узор точек — по опубликованному алгоритму; LightBurn ставит точки своим кодом, узор может отличаться, доля точек — та же.'),
        rampOffer(view, info.scale_size),
        h('figure', {class: 'ge-closeup'}, h('img', {src: info.closeup, alt: `Точки вида «${name}» вблизи`}),
          h('figcaption', {class: 'small muted'}, `Точки вблизи: квадрат ${value(info.closeup_mm, 0)} × ${value(info.closeup_mm, 0)} мм из середины картинки, точка в точку при ${info.dpi} dpi `
            + `(каждая точка — ${info.closeup_px} пикселя экрана), цвет точки — со шкалы.`)),
        h('p', {}, h('strong', {}, `Время гравировки: ≈ ${duration(t.seconds)}`), ` для ${size}${sc ? ` на шкале ${value(sc.time_s_per_cm2, 0)} с/см²` : ''}`
          + (cleaning ? `, из них чистка ≈ ${duration(cleaning.seconds)}` : ''),
          h('span', {class: 'muted small'}, ' — оценка сверху: строки на всю ширину картинки, как в градациях серого; белые места лазер в виде точками пролетает быстрее.')),
        atSize ? h('p', {class: 'small'}, pill(atSize.short, atSize.tone), ' ', atSize.long, h('span', {class: 'muted'}, ' ' + SIZE_ABOUT)) : null,
        h('p', {class: 'small'}, `Файл LightBurn: ${cleaning ? `C00 — чистка ${cleaning.name} по прямоугольнику картинки, первой; C01 — ` : ''}`
          + `слой-изображение в режиме «${name}»: мощность ${value(d.power, 1)} % (Min = Max — каждая точка бьёт на ней), ${settingsText(view.scale, info.dpi)}. `
          + `Картинка — как загружена, ${value(info.size_mm.width, 1)} мм в ширину, левый верхний угол в нуле: точки ставит LightBurn.`),
        h('p', {class: 'muted small'}, 'Подбор серых под цвета, контуры и правила частей — для градаций серого: в виде точками все точки одного цвета, и картинка '
          + 'гравируется как загружена. Вернуться к градациям серого — «Вид» над картинкой; всё, что было для них задано, сохранилось.'));
    }
    const inputs = h('div', {class: 'ge-inputs'}, kind,
      h('label', {class: 'row'}, h('span', {class: 'small'}, 'Ширина, мм'), width),
      h('label', {class: 'row', title: 'Серые подбираются под цвета картинки на этой шкале'}, byColour, h('span', {class: 'small'}, 'Подобрать серые под цвета')),
      choice,
      h('label', {class: 'row', title: 'Контуры: ' + CONTOURS_ABOUT}, contours, h('span', {class: 'small'}, 'Контуры')));
    return {inputs, out, foot, details, show, waiting};
  }

  const OBJECT_NAMES = {background: 'Фон', hair: 'Волосы', face_skin: 'Кожа лица', body_skin: 'Кожа тела', clothes: 'Одежда', other: 'Другое (очки…)',
    lips: 'Губы', eyes: 'Глаза'};
  /** Имя объекта по его ключу: вид, у кусков фона — ещё номер («Фон 2»). */
  const objectName = (key) => { const [kind, piece] = String(key).split('-'); return (OBJECT_NAMES[kind] || kind) + (piece ? ` ${+piece + 1}` : ''); };
  const THEMES = [['warm', 'Тёплая', 'Кожа — самым светлым тёплым цветом шкалы, губы — самым красным, остальное — тёплыми цветами по своей светлоте'],
    ['cool', 'Холодная', 'Кожа и губы тёплые, остальное — холодными цветами шкалы по своей светлоте'],
    ['contrast', 'Контрастная', 'Крупные объекты первыми, каждый — цветом шкалы, самым далёким от уже данных'],
    ['random', 'Случайно', 'Каждому объекту — случайный цвет шкалы; ещё раз — другие цвета']];
  const COLOURING_ABOUT = 'Как в раскраске: каждому объекту — свой основной цвет шкалы. Его светлые и тёмные места ложатся вокруг этого цвета, '
    + 'по соседним цветам шкалы (шаг не больше 5 ΔE, в одном семействе — от золотого не прыгает в синий), поэтому губы остаются губами, очки — очками. '
    + '«Светлее/темнее» сдвигает тона объекта по его семейству. Объект без цвета — «Авто»: как вся картинка при «Сохранить рисунок».';

  /** Вкладка «Раскраска» (0.21.0): объекты картинки — фон и его куски, волосы, кожа, одежда, губы, глаза, другое (очки) — каждому свой
      основной цвет: выберите объект, щёлкните цвет шкалы; «Светлее/темнее»; «Авто» убирает цвет. Темы и «Случайно» дают цвета всем сразу,
      AI — по просьбе своими словами (с картинкой, если разрешено во вкладке «AI»). Любой шаг отменяет «Отменить» в шапке. ``save`` сохраняет
      настройки работы, ``send(path, body)`` — тему или просьбу к AI; оба отдают ошибку или null. */
  function colourTab(id, save, send) {
    const status = h('p', {class: 'small', role: 'status', hidden: true});
    const themes = h('div', {class: 'row'});
    const wish = h('input', {type: 'text', maxlength: 400, 'aria-label': 'Как раскрасить — своими словами', placeholder: 'например: очки золотом, фон синий, губы красные'});
    const aiNote = h('div');
    const palette = h('div', {class: 'ge-palette', role: 'group', 'aria-label': 'Цвета шкалы'});
    const list = h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Ищем объекты картинки…'));
    const notes = h('ul', {class: 'small'});
    const overlay = h('div');
    const blocked = h('p', {class: 'alert warn small', hidden: true});
    let view = null, found = null, foundKey = null, selected = null, asking = false;
    const colours = () => (view && view.colouring) || {};
    const options = () => (found && found.options) || [];
    const hexOf = (c) => { const o = options().find((x) => Math.abs(x.power - c.power) < 0.01); return o ? o.hex : null; };
    /** Цвета объектов ``next`` (ключ → цвет): работа переходит на раскраску по объектам. */
    const colourWith = (next) => save({by_colour: true, colour_choice: 'objects', colouring: next});
    function setColour(key, power) {
      const was = colours()[key];
      colourWith({...colours(), [key]: {power, shift: was ? was.shift : 0}});
    }
    function setShift(key, shift) { colourWith({...colours(), [key]: {...colours()[key], shift}}); }
    function clear(key) { const next = {...colours()}; delete next[key]; colourWith(next); }
    async function ask() {
      if (asking) return;
      if (!wish.value.trim()) { status.textContent = 'Напишите, как раскрасить картинку.'; status.hidden = false; return; }
      asking = true;
      enable();
      status.textContent = 'AI думает… обычно это до минуты.';
      status.hidden = false;
      const failed = await send(`/photo-works/${id}/ai-theme`, {wish: wish.value});
      asking = false;
      status.textContent = failed ? failed.message : '';
      status.hidden = !failed;
      enable();
    }
    const askButton = btn('Раскрасить по просьбе', ask, 'primary btn-small');
    askButton.setAttribute('title', 'AI видит объекты, их цвета на фото и цвета шкалы и даёт каждому объекту основной цвет шкалы');
    wish.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') { ev.preventDefault(); ask(); } });
    const auto = btn('Всё — авто', () => colourWith({}), 'btn-small');
    auto.setAttribute('title', 'Убрать цвета всех объектов: вся картинка как при «Сохранить рисунок»');
    fill(themes, THEMES.map(([name, label, about]) => {
      const b = btn(label, () => send(`/photo-works/${id}/theme`, name === 'random' ? {name, seed: Math.floor(Math.random() * 1e9)} : {name}), 'btn-small');
      b.setAttribute('title', about);
      return b;
    }), auto);
    function enable() {
      const off = !view || dotted(view) || !view.picture;
      for (const b of themes.querySelectorAll('button')) b.disabled = off;
      auto.disabled = off || !Object.keys(colours()).length;
      askButton.disabled = off || asking || !!view.ai_missing;
      wish.disabled = off;
    }
    function rows() {
      if (!found || !view) return;
      const off = dotted(view) || !view.picture;
      const picked = options().length && selected ? (colours()[selected] || null) : null;
      fill(palette, options().map((o) => {
        const b = h('button', {type: 'button', class: 'ge-swatch' + (picked && Math.abs(picked.power - o.power) < 0.01 ? ' is-chosen' : ''), style: `background:${o.hex}`,
          title: `${value(o.power)} % · L* ${value(o.lab[0], 0)}`, 'aria-label': `Цвет шкалы ${value(o.power)} %`, disabled: off || !selected,
          onClick: () => setColour(selected, o.power)});
        return b;
      }));
      fill(list, found.objects.length ? h('ul', {class: 'ge-objects'}, found.objects.map((o) => {
        const c = colours()[o.key] || null;
        const shift = h('input', {type: 'range', min: '-1', max: '1', step: '0.25', value: String(c ? c.shift : 0), disabled: off || !c,
          'aria-label': `Светлее или темнее: ${objectName(o.key)}`, title: 'Темнее ← → светлее'});
        shift.addEventListener('change', () => setShift(o.key, +shift.value));
        const clearIt = btn('Авто', () => clear(o.key), 'btn-small');
        clearIt.disabled = off || !c;
        clearIt.setAttribute('title', 'Убрать цвет объекта: как при «Сохранить рисунок»');
        return h('li', {class: 'ge-object' + (o.key === selected ? ' is-selected' : ''), 'aria-current': o.key === selected ? 'true' : null,
          onClick: (ev) => { if (ev.target.closest('button,input')) return; selected = o.key; rows(); }},
          h('span', {class: 'ge-nowrap'}, h('span', {class: 'sw', style: `background:${o.tint}`, title: 'цвет объекта на картинке объектов'}), objectName(o.key)),
          h('span', {class: 'small muted ge-nowrap'}, `${value(o.share * 100, 1)} % · на фото `, hexChip(o.hex)),
          h('span', {class: 'row ge-nowrap'}, c ? hexChip(hexOf(c)) : pill('авто', 'muted'), c ? `${value(c.power)} %` : null),
          h('span', {class: 'row ge-nowrap'}, h('span', {class: 'small muted'}, 'темнее'), shift, h('span', {class: 'small muted'}, 'светлее'), clearIt));
      })) : h('p', {class: 'muted'}, 'На картинке не нашлось объектов: раскрашивать нечего.'));
      fill(notes, (found.notes || []).map((n) => h('li', {}, I18N.tr(n))));
    }
    async function load() {
      const key = view ? JSON.stringify([view.scale, view.min_power, view.max_power, view.width_mm]) : null;
      if (key === foundKey) { rows(); return; }
      foundKey = key;
      try {
        const next = await get(`/photo-works/${id}/objects`);
        if (key !== foundKey) return;
        found = next;
        if (!selected || !found.objects.some((o) => o.key === selected)) selected = found.objects.length ? found.objects[0].key : null;
        fill(overlay, h('details', {}, h('summary', {class: 'small'}, 'Объекты на картинке'),
          h('img', {class: 'pp-image', src: found.picture, alt: 'Объекты картинки, каждый своим цветом'})));
        rows();
      } catch (e) { if (key === foundKey) fill(list, h('p', {class: 'alert bad'}, e.message)); }
    }
    function show(next) {
      view = next;
      blocked.textContent = dotted(view) ? 'Раскраска по объектам — для градаций серого: в виде точками каждая точка бьёт на одной мощности. Вид меняется кнопкой «Вид» над картинкой; цвета объектов сохранены.'
        : !view.picture ? 'Шкала этой работы не измерена: цветов, чтобы раскрашивать, нет.' : '';
      blocked.hidden = !blocked.textContent;
      if (!wish.value && view.ai_theme) wish.value = view.ai_theme.wish;
      fill(aiNote, view.ai_theme ? h('p', {class: 'small'}, h('strong', {}, 'AI: '), view.ai_theme.note || 'без пояснения',
        h('span', {class: 'muted'}, ` — на «${view.ai_theme.wish}»${view.ai_theme.photo ? ', с картинкой' : ''}`)) : null);
      enable();
      load();
    }
    const el = h('div', {class: 'stack'},
      h('p', {class: 'small'}, COLOURING_ABOUT),
      blocked,
      h('h4', {}, 'Темы'), themes,
      h('div', {class: 'row ge-ask'}, wish, askButton), status, aiNote,
      h('h4', {}, 'Объекты'),
      h('p', {class: 'small muted'}, 'Выберите объект в списке и щёлкните его цвет на полосе цветов шкалы.'),
      palette, list, notes, overlay,
      h('p', {class: 'small muted'}, 'Цвета шкалы — при Min и Max работы, не ближе 8 ΔE друг к другу. Картинку AI получает, только если это разрешено во вкладке «AI». '
        + 'Объекты находит модель людей (кожа, волосы, одежда, другое), губы и глаза — поиск лица, куски фона — по их цвету.'));
    return {el, show};
  }

  const PART_NAMES = {background: 'Фон', hair: 'Волосы', body_skin: 'Кожа тела', face_skin: 'Кожа лица', clothes: 'Одежда', other: 'Другое'};
  const RULES = [['as_is', 'Как есть'], ['photo', 'Цвета фото'], ['neutral', 'Чёрно-белое'], ['colour', 'Цвет'], ['even', 'Один тон']];
  const WITH_TARGET = ['colour', 'even'];
  const AI_MISSING = {library: 'AI недоступен: в окружении приложения нет библиотеки openai (как её поставить — в README). Правила частей можно задать вручную.',
    key: 'AI выключен: не задан ключ языковой модели (OPENAI_API_KEY). Правила частей можно задать вручную.'};

  /** Вкладка «AI» работы (REQ-062): пожелание своими словами, разрешение отправить уменьшенную картинку, «Попросить AI» (от нынешних
      правил: AI меняет то, о чём просят) и «Заново с картинки» (AI начинает с картинки без правил), его ответ; части картинки, найденные
      моделью, с правилом каждой (его можно поменять вручную), цветом-целью и тем, насколько близко к нему подходят серые шкалы, «Все части
      как есть»; части поверх картинки. Серые всегда подбираются на шкале работы, не моделью; любой шаг отменяет «Отменить» в шапке.
      ``save`` сохраняет правила и разрешение, ``ask(wish, fresh)`` спрашивает AI; оба отдают ошибку или null. */
  function aiTab(id, save, ask) {
    const wish = h('textarea', {rows: 3, maxlength: 400, 'aria-label': 'Что изменить в картинке',
      placeholder: 'например: всё как есть, чёрно-белое; платье фиолетовым, ярким; кожу равномерно светлой'});
    const photo = h('input', {type: 'checkbox'});
    const status = h('p', {class: 'small', role: 'status', hidden: true});
    const missing = h('p', {class: 'alert warn small', hidden: true});
    const answer = h('div', {class: 'stack'});
    const table_ = h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Ищем части картинки…'));
    const overlay = h('div');
    let view = null, parts = null, asking = false;
    photo.addEventListener('change', () => save({ai_photo: photo.checked}));
    async function request(fresh) {
      if (asking) return;
      if (!wish.value.trim()) { status.textContent = 'Напишите, что AI должен изменить в картинке.'; status.hidden = false; return; }
      asking = true;
      enable();
      status.textContent = 'AI думает… обычно это до минуты.';
      status.hidden = false;
      const failed = await ask(wish.value, fresh);
      asking = false;
      status.textContent = failed ? failed.message : '';
      status.hidden = !failed;
      enable();
    }
    const button = btn('Попросить AI', () => request(false), 'primary btn-small');
    const again = btn('Заново с картинки', () => request(true), 'btn-small');
    button.setAttribute('title', 'AI видит нынешние правила частей и меняет то, о чём вы просите');
    again.setAttribute('title', 'AI начинает с картинки без правил частей: его ответ заменяет их все');
    const plain = btn('Все части как есть', () => save({rules: []}), 'btn-small');
    plain.setAttribute('title', 'Убрать правила всех частей: картинка гравируется как есть');
    function enable() {
      button.disabled = again.disabled = asking || !!(view && view.ai_missing);
      plain.disabled = !(view && view.rules.length);
    }
    function setRule(part, kind, hex) {
      const others = view.rules.filter((r) => r.part !== part);
      save({rules: kind === 'as_is' ? others : [...others, WITH_TARGET.includes(kind) ? {part, kind, hex} : {part, kind}]});
    }
    function rows() {
      if (!parts) return;
      const report = (view.picture && view.picture.rules_report) || [];
      fill(table_, parts.length ? table(['Часть', 'Доля', 'Цвет', 'Правило', 'ΔE к цели'], parts.map((p) => {
        const name = PART_NAMES[p.part] || p.part;
        const rule = view.rules.find((r) => r.part === p.part) || {kind: 'as_is'};
        const select = h('select', {'aria-label': `Правило: ${name}`}, RULES.map(([kind, label]) => h('option', {value: kind}, label)));
        select.value = rule.kind;
        select.addEventListener('change', () => setRule(p.part, select.value, rule.hex || p.hex));
        const target = WITH_TARGET.includes(rule.kind) ? h('input', {type: 'color', value: rule.hex || p.hex, 'aria-label': `Цвет-цель: ${name}`}) : null;
        if (target) target.addEventListener('change', () => setRule(p.part, rule.kind, target.value));
        const near = report.find((r) => r.part === p.part);
        return [h('span', {class: 'ge-nowrap'}, h('span', {class: 'sw', style: `background:${p.tint}`, title: 'цвет части на картинке частей'}), ` ${name}`),
          h('span', {class: 'ge-nowrap'}, `${value(p.share * 100, 1)} %`), hexChip(p.hex), h('span', {class: 'row ge-rule'}, select, target),
          near && near.median_de != null ? `≈ ${value(near.median_de, 1)}` : h('span', {class: 'muted'}, '—')];
      }), '', true) : h('p', {class: 'muted'}, 'Модель не нашла на картинке частей: правила задать не для чего.'));
    }
    function show(next) {
      view = next;
      photo.checked = !!view.ai_photo;
      missing.textContent = AI_MISSING[view.ai_missing] || '';
      missing.hidden = !view.ai_missing;
      enable();
      if (!wish.value && view.ai) wish.value = view.ai.wish;
      fill(answer, view.ai ? h('p', {class: 'small'}, h('strong', {}, 'AI: '), view.ai.note || 'без пояснения',
        h('span', {class: 'muted'}, ` — на «${view.ai.wish}»${view.ai.fresh ? ', заново с картинки' : ''}${view.ai.photo ? ', с картинкой' : ''}`)) : null);
      rows();
    }
    get(`/photo-works/${id}/parts`).then((found) => {
      parts = found.parts;
      fill(overlay, h('details', {}, h('summary', {class: 'small'}, 'Части на картинке'),
        h('img', {class: 'pp-image', src: found.picture, alt: 'Части картинки, каждая своим цветом'})));
      if (view) rows();
    }, (e) => fill(table_, h('p', {class: 'alert bad'}, e.message)));
    const el = h('div', {class: 'stack'},
      h('p', {class: 'small'}, 'Скажите своими словами, что изменить в картинке. AI предложит правило для каждой части — фона, волос, кожи, одежды; '
        + 'серые подбираются на шкале работы по вашим измерениям, поэтому видно, что на этом титане достижимо.'),
      wish, h('label', {class: 'small ge-check'}, photo, h('span', {}, 'Отправить AI уменьшенную картинку (без этого — только числа: части и их цвета)')),
      h('div', {class: 'row'}, button, again), missing, status, answer,
      h('div', {class: 'row ge-parts-head'}, h('h4', {}, 'Части картинки'), plain), table_, overlay,
      h('p', {class: 'small muted'}, 'Как есть — серые картинки; цвета фото — для каждого пикселя серый с ближайшим цветом на шкале; чёрно-белое — только серые, '
        + 'которые на титане выходят почти серыми; цвет — цель, светлое и тёмное части сохраняются; один тон — один серый на всю часть: он стирает всё внутри неё (глаза, брови и губы — часть кожи лица, '
        + 'поэтому ровную светлую кожу лучше задать цветом). '
        + '«ΔE к цели» — медиана ΔE между желаемым цветом и тем, что даёт шкала. Ответ AI и любое изменение отменяются кнопкой «Отменить» вверху (Ctrl+Z).'));
    return {el, show};
  }

  const PAIR_STATUS = {'Awaiting check': ['ждёт проверки', 'warn'], 'Needs correction': ['нужно исправить', 'warn'], 'Ready to accept': ['готова к принятию', 'warn'],
    Accepted: ['принята', 'ok']};
  const NOT_COMPARED = {no_points: 'Фото не дало ясных цветов этих настроек: слой не найден или серые на нём не различить.',
    kind: 'На фото нет эталонной карты, а цвета шкалы исправлены по карте (или наоборот): сравнить их нельзя.',
    alone: 'Других гравировок с этими настройками нет: сравнивать не с чем, эта гравировка сама стала шкалой.',
    outside: 'Мощности этой гравировки — вне диапазона, измеренного другими гравировками.',
    other_size: (c) => `Других гравировок этих настроек при ширине около ${mm(c.row_mm)} нет (шкала измерена при ${mmList(c.size.measured_mm)}): цвет при другой `
      + 'ширине — не прогноз для этой. Эта гравировка сама стала шкалой для своей ширины.'};
  const notCompared = (c) => (typeof NOT_COMPARED[c.reason] === 'function' ? NOT_COMPARED[c.reason](c) : NOT_COMPARED[c.reason] || c.reason);

  /** Гравировки работы (0.19.3), вверху вкладки «Подтверждение»: «Загрузить фото гравировки» и каждая фотография этой работы — её
      состояние и, когда она принята, каждый серый картинки: какой цвет предсказывали другие гравировки этих настроек и какой получился,
      ΔE между ними, медиана и подтверждено ли (не больше 5 ΔE), как в подтверждении шкалы. ``load(view)`` загружает их заново. */
  function engravingsBlock(id) {
    const el = h('div', {class: 'stack'}, h('p', {class: 'muted small'}, 'Загружаем гравировки работы…'));
    let seq = 0;
    function strip(bands, key, label) {
      return h('div', {class: 'ge-strip-row'}, h('span', {class: 'small muted'}, label),
        h('div', {class: 'ge-strip ge-compare'}, bands.map((b) => h('span', {style: `background:${b[key]}`, title: `серый ${Math.round(b.gray * 255)} · ${value(b.power, 1)} % · ΔE ${value(b.de, 1)}`}))));
    }
    function entry(e) {
      const [label, tone] = PAIR_STATUS[e.status] || [e.status, 'warn'];
      const where = e.status === 'Accepted' ? '/analysis/' + e.pair_id : '/ingest?pair=' + e.pair_id;
      const c = e.check;
      const bands = c ? [...c.bands].sort((a, b) => a.power - b.power) : [];
      return h('li', {class: 'ge-entry stack'},
        h('div', {class: 'ge-entry-head'}, h('span', {}, link(where, `№${e.pair_id} · ${e.photo_name}`), ` · ${when(e.accepted_at || e.created_at)}`), pill(label, tone)),
        e.same_scale === false ? h('p', {class: 'small alert warn'}, `Выгравирована с другими настройками, чем шкала работы: ${settingsText(e.mode)}; сравнивается с гравировками этих настроек.`) : null,
        e.settings && e.settings.power_range ? h('p', {class: 'small muted'}, `Min ${value(e.settings.power_range[0], 1)} % · Max ${value(e.settings.power_range[1], 1)} % в файле`
          + (e.row_mm != null ? ` · ширина ${mm(e.row_mm)}` : '')) : null,
        e.status !== 'Accepted' ? h('p', {class: 'small muted'}, 'Сравнение появится, когда проверку фото примут: откройте её по ссылке.') : null,
        c && c.reason ? h('p', {class: 'small'}, notCompared(c)) : null,
        c && !c.reason ? h('div', {class: 'stack'},
          h('p', {class: 'small'}, pill(c.confirmed ? `подтверждает прогноз: медиана ${value(c.median_de, 1)} ΔE` : `не подтверждает: медиана ${value(c.median_de, 1)} ΔE`, c.confirmed ? 'ok' : 'warn'),
            ` сравнено серых ${c.compared}, в пределах ${c.tolerance_de} ΔE — ${value(c.within * 100, 0)} %, наибольшая разница ${value(c.max_de, 1)} ΔE; `
            + `прогноз — по ${c.others} ${c.others === 1 ? 'другой гравировке' : 'другим гравировкам'} этих настроек`
            + (c.size && c.size.how === 'between' ? `, между измерениями при ширине ${mmList(c.size.from_mm)}.` : c.size && c.size.from_mm.length ? ` при ширине ${mm(c.size.from_mm[0])}.` : '.')),
          strip(bands, 'predicted_hex', 'Прогноз'), strip(bands, 'hex', 'Получилось'),
          h('details', {}, h('summary', {class: 'small'}, 'По серым'),
            table(['Серый', 'Мощность, %', 'Прогноз', 'Получилось', 'ΔE'], bands.map((b) => [String(Math.round(b.gray * 255)), value(b.power, 1),
              hexChip(b.predicted_hex), hexChip(b.hex), b.de > c.tolerance_de ? pill(value(b.de, 1), 'warn') : value(b.de, 1)]), '', true))) : null);
    }
    async function load(view) {
      const mine = ++seq;
      const upload = link(`/ingest?plan=${id}` + (view.scale && view.scale.material_id ? `&material=${view.scale.material_id}` : ''), 'Загрузить фото гравировки');
      try {
        const list = await get(`/photo-works/${id}/engravings`);
        if (mine !== seq) return;
        fill(el, h('h4', {}, 'Гравировки этой работы'),
          h('p', {class: 'small'}, 'Каждый серый выгравированной работы сравнивается с цветом, который для него предсказывают остальные гравировки этих настроек, — так '
            + 'эксперимент подтверждает прогноз или поправляет шкалу. Файл LightBurn работы несёт её имя: фото, загруженное с этим файлом, привяжется к работе само.'),
          h('p', {}, upload),
          list.length ? h('ul', {class: 'ge-entries'}, list.map(entry)) : h('p', {class: 'muted small'}, 'Фото гравировок этой работы пока нет.'));
      } catch (e) { if (mine === seq) fill(el, h('p', {class: 'alert bad'}, e.message), h('p', {}, upload)); }
    }
    return {el, load};
  }

  /** Шапка работы: «← Мои работы», название с карандашом и сводка, «Отменить» и «Повторить» (``step('undo' | 'redo')``), «Шкалы серого»,
      «Сделать копию» и «Файл LightBurn». */
  function workHead(first, step) {
    const title = h('div', {class: 'ge-title'});
    const undo = btn('Отменить', () => step('undo'), 'btn-small'), redo = btn('Повторить', () => step('redo'), 'btn-small');
    const copy = btn('Сделать копию', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/photo-works/${first.id}/copy`, {}); toast('Копия создана и открыта: эта работа осталась как была', 'ok'); go('/photo-engraving?work=' + made.id); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    const file = btn('Файл LightBurn', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { await download(`/photo-works/${first.id}/export.lbrn2`, 'picture.lbrn2'); } catch (e) { fail(e); } finally { self.disabled = false; }
    }, 'primary btn-small');
    const check = h('a', {class: 'btn btn-small', href: `#/photo-preview?work=${first.id}`,
      title: 'Файл работы в «Предпросмотре фотогравировки» — с титаном, лазером и линзой её шкалы'}, 'Файл в предпросмотре');
    const el = h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: '#/photo-engraving'}, '← Мои работы'), title,
      h('div', {class: 'row', role: 'group', 'aria-label': 'Отмена и повтор'}, undo, redo),
      h('a', {class: 'btn btn-small', href: '#/photo-engraving?scales=1'}, 'Шкалы серого'), copy, check, file);
    let shown = first;
    function update(next) {
      shown = next;
      undo.disabled = !(next.undo > 0);
      redo.disabled = !(next.redo > 0);
      undo.setAttribute('title', `Отменить (Ctrl+Z); шагов: ${next.undo || 0}`);
      redo.setAttribute('title', `Повторить (Ctrl+Shift+Z); шагов: ${next.redo || 0}`);
      const pencil = VectorWorkspace.renameButton(next.id, next.name, (stored) => update({...shown, name: stored}), '/photo-works');
      fill(title, h('div', {class: 'vw-name-row'}, h('h2', {title: next.name}, next.name), pencil),
        h('p', {class: 'sub'}, `${next.image_name || 'картинка'} · ${next.image_size[0]} × ${next.image_size[1]} пикс. · ${value(next.width_mm, 1)} × ${value(next.height_mm, 1)} мм`
          + ` · изменена ${when(next.updated_at)}`));
    }
    update(first);
    return {el, update};
  }

  const KIND_ABOUT = {
    power: (k) => `Многоцветная: серый задаёт мощность от Min ${value(k.min_power, 1)} % до Max ${value(k.max_power, 1)} %, мощность на титане — цвет. По измеренной шкале.`,
    dots: (k) => `Точки одного цвета на очищенном титане, тон — сколько точек. Точки ${value(k.power, 1)} %.`,
    edges: (k) => `Точки по краям рисунка, ровные места остаются титаном. Точки ${value(k.power, 1)} %.`};

  const KINDS_ABOUT = 'Градации серого измерены вашими шкалами; виды точками показаны оценкой: точка — цвет шкалы при мощности точек, между точками — '
    + 'очищенный титан. Вид можно поменять в работе в любой момент.';

  /** The tiles of «Какая гравировка?»: every kind that colours titanium, each with the work's picture as it would come out in it (a dot kind
      is an estimate from the scale). The tile of ``current`` is marked with ``tag``; a click on a tile calls ``pick`` with its kind, and
      ``mark(key)`` moves the mark. Shared by the second step of «Новая работа» and the «Вид» button of a work. */
  function kindTiles(id, current, pick, tag) {
    const grid = h('div', {class: 'ge-kinds'}, h('p', {class: 'muted'}, 'Считаем, как картинка выйдет в каждом виде…'));
    let tiles = [];
    const mark = (key) => {
      current = key;
      for (const t of tiles) {
        const on = t.key === key;
        t.el.classList.toggle('is-chosen', on);
        t.el.setAttribute('aria-pressed', String(on));
        fill(t.tag, on ? pill(tag, 'ok') : null);
      }
    };
    get(`/photo-works/${id}/kinds`).then((d) => {
      if (d.problem) { fill(grid, h('p', {class: 'alert warn'}, I18N.tr(d.problem))); return; }
      tiles = d.kinds.map((k) => {
        const name = kindName(k.key);
        const about = (KIND_ABOUT[k.family] || KIND_ABOUT.dots)(k);
        const slot = h('span', {});
        const el = h('button', {type: 'button', class: 'ge-kind', onClick: () => pick(k.key)},
          h('img', {src: k.picture, alt: `Картинка в виде «${name}»`, loading: 'lazy'}),
          h('span', {class: 'ge-kind-head'}, h('strong', {}, name), slot),
          h('span', {class: 'small'}, k.hex ? hexChip(k.hex) : null, k.hex ? ' ' : null, about),
          k.estimate ? h('span', {class: 'small muted'}, k.basis === 'inferred' ? 'оценка; узор LightBurn не опубликован — показан похожий' : 'оценка: этот вид ещё не гравировался') : null);
        return {key: k.key, el, tag: slot};
      });
      fill(grid, tiles.map((t) => t.el));
      mark(current);
    }, (e) => fill(grid, h('p', {class: 'alert bad'}, e.message)));
    return {el: grid, mark};
  }

  /** «Вид» of a work: «Какая гравировка?» with the work's picture in each kind and its kind marked; a click on another kind switches the
      work to it («Отменить» takes it back). */
  function kindChooser(id, current, choose) {
    const tiles = kindTiles(id, current, (key) => { dialog.close(); if (key !== current) choose(key); }, 'сейчас');
    const dialog = modal('Какая гравировка?', h('div', {class: 'stack'},
      h('p', {class: 'small'}, 'Под каждым видом — картинка работы, какой она выйдет на титане на её шкале. ' + KINDS_ABOUT), tiles.el),
      [{label: 'Закрыть', run: (m) => m.close()}]);
    return dialog;
  }

  /** Работа на один экран: шкалы слева (выбранная — шкала работы), картинка и её прогноз посередине, вкладки справа. Изменения уходят на
      сервер по очереди, в том порядке, в каком сделаны, и показывается ответ на последнее; другая шкала приходит со своими Min и Max. */
  async function workScreen(id) {
    const [first, {scales}] = await Promise.all([get('/photo-works/' + id), get('/grey-scales')]);
    let view = first, detail = null, shownKey = null, seq = 0, queue = Promise.resolve();
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const list = h('div', {class: 'ge-scales'});
    const slots = newSlots();
    const picture = workPicture(save, () => kindChooser(id, view.kind || GRAYSCALE, (kind) => save({kind})));
    const head = workHead(view, step);
    const ai = aiTab(id, save, (wish, fresh) => send(`/photo-works/${id}/ai`, {wish, fresh}));
    const colour = colourTab(id, save, (path, body) => send(path, body));
    const engraved = engravingsBlock(id);
    const tabs = App.tabs([['picture', 'Картинка', picture.details], ['colour', 'Раскраска', colour.el], ['ai', 'AI', ai.el], ['scale', 'Шкала', slots.scale],
      ['confirm', 'Подтверждение', h('div', {class: 'stack'}, engraved.el, slots.confirm)],
      ['points', 'Точки', slots.points]], {initial: 'picture', remember: 'ge.work.tab', label: 'Картинка и шкала', prefix: 'ge-tab'});
    const chosen = () => scales.find((sc) => sameScale(sc, view.scale)) || null;
    const scaleKey = (v, mode = v.scale) => `${modeQuery(mode)}&row_mm=${v.width_mm}&kind=${v.kind || GRAYSCALE}`;   // at the work's width, for its kind
    const cards = (current) => fill(list, scales.map((item) => scaleCard(item, item === current, () => pick(item))));

    function showScale() {
      if (detail) detail.stop();
      const sc = chosen();
      shownKey = scaleKey(view);
      cards(sc);
      engraved.load(view);
      const dot = dotted(view) && view.dot_power != null ? {power: view.dot_power, changed: (p) => save({dot_power: p})} : null;
      if (sc) detail = scaleDetail(sc, slots, {initial: [view.min_power, view.max_power], changed: (lo, hi) => save({min_power: lo, max_power: hi}), rowMm: view.width_mm, dot});
      else { detail = null; emptySlots(slots, 'Шкала этой работы не измерена: выберите шкалу слева.'); }
    }
    function shown() {
      head.update(view);
      picture.show(view, chosen());
      colour.show(view);
      ai.show(view);
      if (scaleKey(view) !== shownKey) showScale();
    }
    /** One change of the work (``path`` with ``body``): sent after those before it; the answer to the last one is shown. With ``again``
        the scale is shown anew from the answer (an undo or redo can bring back other Min and Max on the same scale). The promise gives the
        error of this change, or null. */
    function send(path, body, again = false) {
      const mine = ++seq;
      error.hidden = true;
      picture.waiting();
      queue = queue.then(() => post(path, body)).then((next) => { view = next; if (mine === seq) { if (again) shownKey = null; shown(); } return null; },
        (e) => { if (mine === seq) { error.textContent = e.message; error.hidden = false; shown(); } return e; });
      return queue;
    }
    function save(changes) { return send(`/photo-works/${id}/settings`, changes); }
    /** «Отменить» или «Повторить» (``kind``): работа становится такой, какой была до последнего изменения (или после отменённого). */
    function step(kind) { return (view[kind] || 0) > 0 ? send(`/photo-works/${id}/${kind}`, {}, true) : Promise.resolve(null); }
    /** Другая шкала: картинка остаётся, Min и Max становятся измеренным диапазоном новой шкалы (их присылает сервер). */
    function pick(item) {
      if (scaleKey(view, item.mode) === shownKey) return;
      if (detail) detail.stop();
      detail = null;
      shownKey = null;
      cards(item);
      emptySlots(slots, 'Загружаем шкалу…');
      save({scale: item.mode});
    }
    shown();
    const root = h('div', {class: 'os ge'});
    const key = (ev) => {
      if (!root.isConnected) { if (keys === key) keys = null; return; }
      const t = ev.target;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable)) return;   // в поле ввода клавиши — его
      if (document.querySelector('.modal-bg')) return;
      const z = ev.code === 'KeyZ' || (ev.key || '').toLowerCase() === 'z', y = ev.code === 'KeyY' || (ev.key || '').toLowerCase() === 'y';
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (z || y)) { ev.preventDefault(); step(z && !ev.shiftKey ? 'undo' : 'redo'); }
    };
    keys = key;
    return fill(root, head.el, h('div', {class: 'os-body ge-body'},
      h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, `Шкала работы (измерено ${scales.length})`)),
        h('div', {class: 'os-scroll'}, scales.length ? list : h('p', {class: 'muted'}, 'Измеренных шкал нет: выгравируйте пластину «Шкалы серого» и добавьте её фотографию.'))),
      h('div', {class: 'os-col ge-centre'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Картинка на шкале'), slots.title),
        h('div', {class: 'ge-work'}, picture.inputs, slots.powers, slots.error, error, slots.bar, picture.out, picture.foot)),
      h('div', {class: 'os-col ge-right'}, tabs.list, h('div', {class: 'os-scroll'}, tabs.panels))));
  }

  // ---- список работ, новая работа, шкалы серого ----------------------------------------------------------------------------------------

  /** «Новая работа» in two steps of one dialog. Step 1: the picture, the name and the width on titanium; «Дальше» makes the work on ``scale``
      (from the scales page) or the best measured scale, Min and Max its measured span. Step 2: «Какая гравировка?» with the picture in each
      kind, grayscale chosen; a click on a tile chooses its kind and «Создать» keeps the work in it and opens the work. Leaving step 2 any
      other way («Назад», ×, Escape, a click outside) deletes the work step 1 made; «Назад» returns to step 1 with its fields as they were. */
  function newWork(scale) {
    const fileIn = h('input', {type: 'file', accept: PICTURES, 'aria-label': 'Картинка'});
    const name = h('input', {autocomplete: 'off', 'aria-label': 'Название работы', placeholder: 'по имени файла'});
    const width = h('input', {type: 'number', min: '1', max: '1000', step: 'any', value: '50', 'aria-label': 'Ширина на титане, мм'});
    fileIn.addEventListener('change', () => {
      const file = fileIn.files && fileIn.files[0];
      if (file && !name.value.trim()) name.value = file.name.replace(/\.[^.]+$/, '');
    });
    const fields = h('div', {class: 'stack'}, App.filePick(fileIn, 'Выбрать картинку'), field('Название', name), field('Ширина на титане, мм', width),
      h('p', {class: 'small muted'}, (scale ? `Шкала: ${settingsText(scale)}. Min и Max — её измеренный диапазон; шкалу, Min, Max, ширину и подбор серых можно поменять в работе.`
        : 'Шкала — лучшая из измеренных, Min и Max — её измеренный диапазон; шкалу, Min, Max, ширину и подбор серых можно поменять в работе.')
        + ' Шаг 2 — какая гравировка: ваша картинка в каждом виде.'));
    const pictureStep = () => modal('Новая работа · шаг 1 из 2: картинка', fields, [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Дальше →', cls: 'primary', run: async (m) => {
        const file = fileIn.files && fileIn.files[0];
        if (!file) throw new Error('Выберите картинку (PNG, JPEG, TIFF)');
        const fd = new FormData();
        fd.append('picture', file, file.name);
        fd.append('name', name.value);
        fd.append('width_mm', width.value);
        if (scale) fd.append('scale', JSON.stringify(scale));
        const made = await form('/photo-works', fd);
        m.close();
        kindStep(made.id);
      }}]);
    const kindStep = (id) => {
      let chosen = GRAYSCALE, kept = false, back = false;
      const label = () => `Создать в «${kindName(chosen)}»`;
      const tiles = kindTiles(id, chosen, (key) => { chosen = key; tiles.mark(key); create.textContent = label(); }, 'выбрано');
      const dialog = modal('Новая работа · шаг 2 из 2: какая гравировка?', h('div', {class: 'stack'},
        h('p', {class: 'small'}, 'Под каждым видом — ваша картинка, какой она выйдет на титане на шкале работы; щелчок выбирает вид. ' + KINDS_ABOUT), tiles.el), [
        {label: '← Назад', run: (m) => { back = true; m.close(); }},
        {label: label(), cls: 'primary', run: async (m) => {
          kept = true;                                      // from here the work stays, even if the dialog is closed while it is saved
          try { if (chosen !== GRAYSCALE) await post(`/photo-works/${id}/settings`, {kind: chosen}); }
          catch (e) { kept = false; throw e; }
          m.close();
          go(`/photo-engraving?work=${id}`);
        }}], () => {
        if (kept) return;
        del('/plans/' + id).catch(fail);
        if (back) pictureStep();
      });
      const buttons = dialog.el.querySelectorAll('button');
      const create = buttons[buttons.length - 1];
    };
    pictureStep();
  }

  const plateButton = (devices, materials, cls) => btn('Пластина «Шкалы серого»', () => PlateDialog.open(devices, materials, null, {type: 'grey_scales'}), cls,
    !devices.some((d) => d.lens));

  function workCard(w) {
    const open = () => go('/photo-engraving?work=' + w.id);
    const copy = btn('Сделать копию', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/photo-works/${w.id}/copy`, {}); toast('Копия создана и открыта: старая работа осталась как была', 'ok'); go('/photo-engraving?work=' + made.id); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    const remove = btn('Удалить', () => confirmBox(`Удалить работу «${w.name}»?`,
      'Исчезнут картинка и настройки работы; вернуть работу будет нельзя. Чтобы сохранить её, сначала нажмите «Сделать копию».',
      'Удалить', async () => { await del('/plans/' + w.id); toast('Работа удалена', 'ok'); App.render(); }), 'danger btn-small');
    const thumb = h('a', {class: 'vw-thumb', href: '#/photo-engraving?work=' + w.id, 'aria-label': 'Открыть работу ' + w.name},
      h('img', {src: `/api/photo-works/${w.id}/thumb.png?v=${encodeURIComponent(w.updated_at)}`, alt: '', loading: 'lazy'}));
    const title = h('h3', {}, w.name);
    const pencil = VectorWorkspace.renameButton(w.id, w.name, (stored) => { w.name = stored; fill(title, stored); thumb.setAttribute('aria-label', 'Открыть работу ' + stored); }, '/photo-works');
    return h('article', {class: 'card vw-work-card'}, thumb,
      h('div', {class: 'stack vw-work-info'}, h('div', {class: 'vw-name-row'}, title, pencil),
        h('p', {class: 'small'}, `${value(w.width_mm, 1)} × ${value(w.height_mm, 1)} мм · картинка ${w.image_size[0]} × ${w.image_size[1]} пикс.`),
        h('p', {class: 'small'}, settingsText(w.scale, w.dpi)),
        dotted(w) ? h('p', {class: 'small'}, `${materialLabel(w.material)} · ${kindName(w.kind)} · точки ${value(w.dot_power, 1)} % (оценка по шкале)`)
          : h('p', {class: 'small'}, `${materialLabel(w.material)} · Min ${value(w.min_power, 1)} % · Max ${value(w.max_power, 1)} %${w.by_colour ? ` · серые подобраны под цвета: ${w.colour_choice === 'nearest' ? 'ближайший цвет' : w.colour_choice === 'objects' ? 'раскраска по объектам' : 'рисунок сохранён'}` : ''}`
            + (w.rules && w.rules.length ? ` · правил для частей: ${w.rules.length}` : '')),
        h('p', {class: 'small'}, `Гравировка ≈ ${duration(w.time.seconds)}`),
        h('p', {class: 'small muted'}, `изменена ${when(w.updated_at)}`),
        h('div', {class: 'row'}, btn('Открыть', open, 'primary btn-small'), copy, remove)));
  }

  /** «Мои работы»: сохранённые работы и «Новая работа»; оттуда же — шкалы серого и пластина для их измерения. */
  async function listScreen() {
    const [works, devices, materials] = await Promise.all([get('/photo-works'), get('/devices'), get('/materials')]);
    const create = () => btn('Новая работа', () => newWork(null), 'primary');
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Фотогравировка'),
        h('p', {class: 'sub'}, 'Мои работы: картинка в режиме градаций серого на измеренной шкале — какой она выйдет на титане, сколько гравируется, файл LightBurn. '
          + 'Хранятся на этом компьютере. Откройте работу, чтобы продолжить, или сделайте копию, чтобы переделать, не потеряв прежнюю.')),
        h('span', {class: 'spacer'}), h('a', {class: 'btn', href: '#/photo-engraving?scales=1'}, 'Шкалы серого'), plateButton(devices, materials, ''), create()),
      h('p', {class: 'small muted'}, 'Другие виды: ', link('/photo-preview', 'прогноз по файлу LightBurn'), ' · ', link('/photo', 'непрерывная полосами'), '.'),
      works.length ? h('div', {class: 'vw-works'}, works.map(workCard))
        : h('div', {class: 'card empty'}, h('h3', {}, 'Работ пока нет'),
          h('p', {class: 'muted'}, 'Выберите картинку, её ширину на титане и название: работа покажет картинку рядом с прогнозом на лучшей измеренной шкале. '
            + 'Если шкал ещё нет, сначала выгравируйте пластину «Шкалы серого» и добавьте её фотографию в «Эксперименты».'), create()));
  }

  function kindsBlock() {
    const rows = Object.entries(PhotoModes.MODES).map(([key, m]) => h('li', {class: 'ge-entry'},
      h('div', {class: 'ge-entry-head'}, h('strong', {}, m.label),
        key === 'grayscale' ? pill('здесь: по шкалам «серый → цвет»', 'ok') : m.family === 'depth' ? h('span', {class: 'muted small'}, PhotoModes.PREDICT[m.predict])
          : pill('в работе — оценка по шкале: точка цвета шкалы при своей мощности', 'warn')),
      h('div', {class: 'small'}, h('span', {class: 'muted'}, 'Серый задаёт: '), PhotoModes.FAMILY[m.family]),
      h('div', {class: 'small'}, h('span', {class: 'muted'}, 'Важно в настройках: '), m.settings)));
    return h('div', {class: 'stack'}, h('p', {class: 'small'}, ABOUT), h('h4', {}, 'Виды фотогравировки LightBurn и что здесь предсказывается'),
      h('ul', {class: 'ge-entries'}, rows),
      h('p', {class: 'small muted'}, 'Шаг строк: в градациях серого он один на всю картинку (dpi = 25,4 / шаг). Слишком частые строки, как у цветных заливок, перегревают металл, '
        + 'и серый перестаёт давать разные цвета; пластина «Шкалы серого» по умолчанию сравнивает 2000, 1500, 1200 и 1000 dpi (0,0127–0,0254 мм).'));
  }

  const ABOUT = 'Режим градаций серого: все настройки постоянны, кроме мощности. Серый картинки задаёт мощность от Min до Max, а мощность на титане даёт цвет — '
    + 'поэтому одна серая картинка выходит несколькими цветами. Шкала показывает, какой серый каким цветом выходит при ваших настройках, по вашим измерениям.';

  /** «Шкалы серого» на один экран: шкалы слева, Min, Max, полоса и таблица серых посередине, подтверждение, точки и виды справа. */
  async function scalesScreen(wanted) {
    const [{scales}, devices, materials] = await Promise.all([get('/grey-scales'), get('/devices'), get('/materials')]);
    let current = null, detail = null;
    const create = btn('Новая работа на этой шкале', () => newWork(current.mode), 'primary btn-small');
    const head = h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: '#/photo-engraving'}, '← Мои работы'),
      h('div', {class: 'ge-title'}, h('h2', {}, 'Шкалы серого'), h('p', {class: 'sub'}, ABOUT)), plateButton(devices, materials, 'btn-small'),
      scales.length ? create : null);
    if (!scales.length) {
      return h('div', {class: 'os ge'}, head, h('div', {class: 'os-body ge-empty'},
        h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Шкал пока нет')),
          h('div', {class: 'os-scroll stack'}, h('p', {}, 'Шкала появляется, когда принята фотография гравировки в режиме градаций серого: пластины «Шкалы серого» '
            + 'или вашей фотогравировки (слой-изображение в файле LightBurn).'), kindsBlock()))));
    }
    const list = h('div', {class: 'ge-scales'});
    const slots = newSlots();
    const tabs = App.tabs([['confirm', 'Подтверждение', slots.confirm], ['points', 'Точки', slots.points], ['kinds', 'Виды', kindsBlock()]],
      {initial: 'confirm', remember: 'ge.tab', label: 'Шкала', prefix: 'ge-tab'});
    const choose = (sc) => {
      if (detail) detail.stop();
      current = sc;
      fill(list, scales.map((item) => scaleCard(item, item === sc, () => choose(item))));
      detail = scaleDetail(sc, slots);
    };
    choose(scales.find((sc) => modeQuery(sc.mode) === wanted) || scales[0]);
    return h('div', {class: 'os ge'}, head, h('div', {class: 'os-body ge-body'},
      h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, `Измеренные шкалы (${scales.length})`)), h('div', {class: 'os-scroll'}, list)),
      h('div', {class: 'os-col ge-centre'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Серый → цвет'), slots.title),
        h('div', {class: 'ge-work'}, slots.powers, slots.error, slots.bar, h('div', {class: 'ge-table'}, slots.scale))),
      h('div', {class: 'os-col ge-right'}, tabs.list, h('div', {class: 'os-scroll'}, tabs.panels))));
  }

  App.register({id: 'photo-engraving', async render(ctx) {
    if (ctx.query.work) return workScreen(encodeURIComponent(ctx.query.work));
    if (ctx.query.scales || ctx.query.scale) return scalesScreen(ctx.query.scale);
    return listScreen();
  }});
})();
