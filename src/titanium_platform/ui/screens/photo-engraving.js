/* Фотогравировка (REQ-059, REQ-061): работы в режиме градаций серого на измеренных шкалах. Шкала — постоянные настройки (лазер, линза,
   титан, скорость, частота, импульс, шаг строк, проходы) с измеренной кривой «мощность → цвет»; серый картинки задаёт мощность от Min
   (белый) до Max (чёрный), и на титане мощность даёт цвет.
   Работа — картинка на шкале, как векторная работа (DEC-104): список «Мои работы» (открыть, сделать копию, переименовать, удалить),
   «Новая работа» (картинка, название, ширина), сама работа на один экран: шкалы слева, картинка рядом с прогнозом посередине, справа
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
      h('span', {class: 'small muted'}, `${materialLabel(sc.material)} · ${kinds} · ${value(sc.time_s_per_cm2, 0)} с/см²`),
      sc.sizes && sc.sizes.length ? h('span', {class: 'small muted'}, `измерена при ширине ${mmList(sc.sizes.map((z) => z.row_mm))}`) : null,
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
      ``stop()`` — шкала больше не показывается: её отложенное изменение и поздние ответы не применяются. */
  function scaleDetail(sc, slots, {initial = null, changed = null, rowMm = null} = {}) {
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
    const slider = (label, short, start) => {
      const range = h('input', {type: 'range', min: 0, max: 100, step: 0.1, value: start, 'aria-label': label});
      const exact = h('input', {type: 'number', min: 0, max: 100, step: 'any', value: start, 'aria-label': label});
      range.addEventListener('input', () => { exact.value = range.value; schedule(); });
      exact.addEventListener('change', () => { range.value = exact.value; schedule(); });
      return {exact, box: h('label', {class: 'ge-power', title: label}, h('span', {class: 'small'}, short), range, exact)};
    };
    const [lo0, hi0] = initial || [Math.ceil(span[0] * 10 - 1e-9) / 10, Math.floor(span[1] * 10 + 1e-9) / 10];
    const low = slider('Min мощность, % (белый)', 'Min, %', lo0);
    const high = slider('Max мощность, % (чёрный)', 'Max, %', hi0);
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const loading = () => h('p', {class: 'muted'}, 'Загружаем шкалу…');
    fill(slots.title, settingsText(sc.mode, sc.dpi));
    slots.title.setAttribute('title', `${settingsText(sc.mode, sc.dpi)} · ${materialLabel(sc.material)}`);
    fill(slots.powers, low.box, high.box, widths);
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
        fill(slots.bar, greyBar(levels));
        fill(slots.scale,
          h('p', {class: 'small muted'}, `${materialLabel(sc.material)}. Измерено от ${value(span[0], 1)} до ${value(span[1], 1)} %. Серый картинки становится мощностью линейно: `
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
    const make = btn('Проба на ширине работы', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/photo-works/${view.id}/width-ramp`, {}); toast(`Создано: ${made.name}`, 'ok'); go('/experiment/plan-' + made.plan_id); }
      catch (e) { fail(e); self.disabled = false; }
    }, size && size.how === 'measured' ? 'btn-small' : 'primary btn-small');
    return h('p', {class: 'small'}, make, h('span', {class: 'muted'}, ` Пластина с одной полоской серого ${mm(view.width_mm)} в ширину на настройках шкалы, `
      + `Min ${value(view.min_power, 1)} % и Max ${value(view.max_power, 1)} %: выгравируйте её, сфотографируйте и загрузите — шкала будет измерена при ширине работы.`));
  }

  const CHOICES = [['drawing', 'Сохранить рисунок'], ['nearest', 'Ближайший цвет']];
  const CHOICE_ABOUT = '«Сохранить рисунок»: тона картинки раскладываются по одной плавной полосе шкалы — от самого светлого её цвета к самому тёмному, '
    + 'светлота только убывает, оттенок не скачет; соседние тона получают соседние мощности, поэтому кожа остаётся ровной, с градиентом, без пятен. '
    + 'Зерно и квадраты JPEG сглаживаются (до 0,25 мм), губы, глаза и тени лица (до 1,5 мм) подчёркиваются, средние тона светлеют. Оттенки картинки '
    + 'не повторяются — вся картинка в цветах этой полосы. «Ближайший цвет»: серый, который на шкале даёт ближайший цвет, даже если он намного '
    + 'темнее или светлее.';
  const CONTOURS_ABOUT = 'только при подборе серых под цвета: где граница картинки (губы, глаза, блики) на титане потерялась бы, она обводится '
    + 'линией 0,3 мм — самым тёмным серым шкалы, на тёмном или у светлого блика — самым светлым. Внутри части с правилом «Один тон» не обводится.';

  /** Что сказать о подборе серых (``colour_match`` с сервера): насколько сохранён рисунок или насколько близки цвета. */
  function matchText(match) {
    if (!match) return null;
    const used = `использовано серых ${match.greys_used} из ${match.greys_available}`;
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
  function workPicture(save) {
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
      width.value = String(view.width_mm);
      byColour.checked = !!view.by_colour;
      choice.value = view.colour_choice || 'drawing';
      choice.disabled = !view.by_colour;
      contours.checked = !!view.contours;
      contours.disabled = !view.by_colour;
      const info = view.picture;
      if (!info) {
        fill(out, h('div', {class: 'ge-placeholder stack'}, h('p', {class: 'alert warn'}, I18N.tr(view.problem)),
          h('p', {class: 'muted'}, 'Выберите измеренную шкалу слева: картинка останется, Min и Max станут измеренным диапазоном шкалы.')));
        fill(foot);
        fill(details, h('p', {class: 'muted'}, 'Прогноза нет: шкала этой работы не измерена.'));
        return;
      }
      const t = info.time;
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
        h('p', {}, h('strong', {}, `Время гравировки: ≈ ${duration(t.seconds)}`), ` для ${size}${sc ? ` на шкале ${value(sc.time_s_per_cm2, 0)} с/см²` : ''}`,
          h('span', {class: 'muted small'}, ' — оценка: строки на всю ширину картинки (в градациях серого бьёт и белый — на Min), скорость, шаг строк и проходы; разгон и переходы не учтены.')),
        info.outside_share > 0 ? h('p', {class: 'alert warn'}, `${value(info.outside_share * 100, 1)} % картинки требует мощности вне измеренной шкалы: там прогноза нет, места заштрихованы.`) : null,
        matchText(info.colour_match),
        contoursText(view, info),
        atSize ? h('p', {class: 'small'}, pill(atSize.short, atSize.tone), ' ', atSize.long, h('span', {class: 'muted'}, ' ' + SIZE_ABOUT)) : null,
        rampOffer(view, info.scale_size),
        h('p', {class: 'small'}, `Файл LightBurn: один слой-изображение C00 в режиме градаций серого: Min ${value(info.power_range[0], 1)} %, Max ${value(info.power_range[1], 1)} %, `
          + `${settingsText(view.scale, info.dpi)}. Картинка ${value(info.size_mm.width, 1)} мм в ширину, левый верхний угол в нуле.`),
        h('ul', {class: 'small'}, info.notes.map((n) => h('li', {}, I18N.tr(n)))),
        info.by_colour ? h('details', {}, h('summary', {class: 'small'}, 'Исходная цветная картинка'),
          h('img', {class: 'pp-image', src: `/api/photo-works/${view.id}/picture`, alt: 'Исходная картинка'})) : null,
        h('p', {class: 'muted small'}, 'Серая картинка гравируется как есть. Цветная — либо как LightBurn переводит её в серый (по яркости), либо с подбором серых под цвета. '
          + CHOICE_ABOUT + ' Контуры: ' + CONTOURS_ABOUT + ' Прогноз и файл LightBurn — одна и та же картинка; прогноз пересчитывается сам, когда меняются шкала, Min и Max, '
          + 'ширина, подбор или контуры.'));
    }
    const inputs = h('div', {class: 'ge-inputs'},
      h('label', {class: 'row'}, h('span', {class: 'small'}, 'Ширина, мм'), width),
      h('label', {class: 'row', title: 'Серые подбираются под цвета картинки на этой шкале'}, byColour, h('span', {class: 'small'}, 'Подобрать серые под цвета')),
      choice,
      h('label', {class: 'row', title: 'Контуры: ' + CONTOURS_ABOUT}, contours, h('span', {class: 'small'}, 'Контуры')));
    return {inputs, out, foot, details, show, waiting};
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
    const el = h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: '#/photo-engraving'}, '← Мои работы'), title,
      h('div', {class: 'row', role: 'group', 'aria-label': 'Отмена и повтор'}, undo, redo),
      h('a', {class: 'btn btn-small', href: '#/photo-engraving?scales=1'}, 'Шкалы серого'), copy, file);
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

  /** Работа на один экран: шкалы слева (выбранная — шкала работы), картинка и её прогноз посередине, вкладки справа. Изменения уходят на
      сервер по очереди, в том порядке, в каком сделаны, и показывается ответ на последнее; другая шкала приходит со своими Min и Max. */
  async function workScreen(id) {
    const [first, {scales}] = await Promise.all([get('/photo-works/' + id), get('/grey-scales')]);
    let view = first, detail = null, shownKey = null, seq = 0, queue = Promise.resolve();
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const list = h('div', {class: 'ge-scales'});
    const slots = newSlots();
    const picture = workPicture(save);
    const head = workHead(view, step);
    const ai = aiTab(id, save, (wish, fresh) => send(`/photo-works/${id}/ai`, {wish, fresh}));
    const engraved = engravingsBlock(id);
    const tabs = App.tabs([['picture', 'Картинка', picture.details], ['ai', 'AI', ai.el], ['scale', 'Шкала', slots.scale],
      ['confirm', 'Подтверждение', h('div', {class: 'stack'}, engraved.el, slots.confirm)],
      ['points', 'Точки', slots.points]], {initial: 'picture', remember: 'ge.work.tab', label: 'Картинка и шкала', prefix: 'ge-tab'});
    const chosen = () => scales.find((sc) => modeQuery(sc.mode) === modeQuery(view.scale)) || null;
    const scaleKey = (v) => `${modeQuery(v.scale)}&row_mm=${v.width_mm}`;                 // the scale is shown at the work's width
    const cards = (current) => fill(list, scales.map((item) => scaleCard(item, item === current, () => pick(item))));

    function showScale() {
      if (detail) detail.stop();
      const sc = chosen();
      shownKey = scaleKey(view);
      cards(sc);
      engraved.load(view);
      if (sc) detail = scaleDetail(sc, slots, {initial: [view.min_power, view.max_power], changed: (lo, hi) => save({min_power: lo, max_power: hi}), rowMm: view.width_mm});
      else { detail = null; emptySlots(slots, 'Шкала этой работы не измерена: выберите шкалу слева.'); }
    }
    function shown() {
      head.update(view);
      picture.show(view, chosen());
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
      if (`${modeQuery(item.mode)}&row_mm=${view.width_mm}` === shownKey) return;
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

  /** «Новая работа»: картинка, название и ширина на титане. Шкала — ``scale`` (со страницы шкал) или лучшая из измеренных, Min и Max — её
      измеренный диапазон; всё это меняется в работе. Работа открывается сразу. */
  function newWork(scale) {
    const fileIn = h('input', {type: 'file', accept: PICTURES, 'aria-label': 'Картинка'});
    const name = h('input', {autocomplete: 'off', 'aria-label': 'Название работы', placeholder: 'по имени файла'});
    const width = h('input', {type: 'number', min: '1', max: '1000', step: 'any', value: '50', 'aria-label': 'Ширина на титане, мм'});
    fileIn.addEventListener('change', () => {
      const file = fileIn.files && fileIn.files[0];
      if (file && !name.value.trim()) name.value = file.name.replace(/\.[^.]+$/, '');
    });
    modal('Новая работа', h('div', {class: 'stack'}, App.filePick(fileIn, 'Выбрать картинку'), field('Название', name), field('Ширина на титане, мм', width),
      h('p', {class: 'small muted'}, scale ? `Шкала: ${settingsText(scale)}. Min и Max — её измеренный диапазон; шкалу, Min, Max, ширину и подбор серых можно поменять в работе.`
        : 'Шкала — лучшая из измеренных, Min и Max — её измеренный диапазон; шкалу, Min, Max, ширину и подбор серых можно поменять в работе.')), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Создать', cls: 'primary', run: async (m) => {
        const file = fileIn.files && fileIn.files[0];
        if (!file) throw new Error('Выберите картинку (PNG, JPEG, TIFF)');
        const fd = new FormData();
        fd.append('picture', file, file.name);
        fd.append('name', name.value);
        fd.append('width_mm', width.value);
        if (scale) fd.append('scale', JSON.stringify(scale));
        const made = await form('/photo-works', fd);
        m.close();
        go('/photo-engraving?work=' + made.id);
      }}]);
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
        h('p', {class: 'small'}, `${materialLabel(w.material)} · Min ${value(w.min_power, 1)} % · Max ${value(w.max_power, 1)} %${w.by_colour ? ` · серые подобраны под цвета: ${w.colour_choice === 'nearest' ? 'ближайший цвет' : 'рисунок сохранён'}` : ''}`
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
        key === 'grayscale' ? pill('здесь: по шкалам «серый → цвет»', 'ok') : m.predict === 'profile' ? link('/photo-preview', 'прогноз по файлу LightBurn') : h('span', {class: 'muted small'}, PhotoModes.PREDICT[m.predict])),
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
