/* Фотозоны векторной работы (REQ-073, DEC-114): выделенные области гравируются фотогравировкой самой картинки работы — градациями серого
   на измеренной шкале или видом точками (Джарвис и другие) — вместо плоских цветов титана, и картина выходит частью векторной, частью
   фотогравировкой. Вкладка «Фото» редактора: каждая фотозона с видом гравировки (плитки зоны в каждом виде — щелчок выбирает), шкалой
   серого (палитрой: у каждой измеренной шкалы полоса её цветов, щелчок выбирает), Min и Max или мощностью точек и «Цветами по картинке»;
   цвет точек — со шкалы или с карты цветов («Цвет с карты», 0.27.0); «Открыть» показывает зону на своём экране, как работу фотогравировки
   (vector-zone.js, 0.23.0), там же яркость, контраст и гамма картинки. Каждое изменение — одно действие
   редактора: оно отменяется и повторяется, как любое другое. Картинку зоны на рисунке работы показывает редактор (vector-editor.js). */
'use strict';
const VectorPhoto = (() => {
  const {h, fill, btn, get, go, num} = App;
  const GRAYSCALE = 'grayscale';
  const SCALE_KEYS = ['speed', 'frequency', 'pulse_width', 'line_interval', 'passes'];
  const scalesCache = new Map();
  const kindsCache = new Map();
  const value = (v, d = 1) => (v == null ? '—' : String(+(+v).toFixed(d)));                 // как числа редактора: точка, без лишних нулей
  const kindName = (key) => { const t = PhotoModes.label(key); return t.charAt(0).toUpperCase() + t.slice(1); };
  const dotted = (zone) => zone.kind !== GRAYSCALE;
  const sameScale = (mode, scale) => SCALE_KEYS.every((k) => String(mode[k] ?? '') === String(scale[k] ?? ''));
  const settingsText = (m) => `${value(m.speed, 0)} мм/с · ${value(m.frequency, 0)} кГц · ${m.pulse_width == null ? 'импульс не указан' : value(m.pulse_width, 0) + ' нс'}`;
  const stepText = (m) => `шаг ${value(m.line_interval, 4)} мм`;
  const area = (mm2) => (mm2 == null ? '—' : mm2 >= 100 ? `${num(mm2 / 100, 2)} см²` : `${num(mm2, 1)} мм²`);
  const layerOf = (zone) => (zone.index == null ? '' : `C${String(zone.index).padStart(2, '0')}`);
  /** Что зона выжжет — коротко, для заголовка и строки слоя. */
  const zoneSummary = (zone) => [layerOf(zone), kindName(zone.kind),
    !dotted(zone) ? `${value(zone.min_power)}–${value(zone.max_power)} %`
      : zone.dot_recipe ? `точки ${value(zone.dot_recipe.settings.power)} % ${recipeFrom(zone.dot_recipe)}` : `точки ${value(zone.dot_power)} %`,
    zone.tone_used ? `яркость ${value(zone.tone.brightness, 0)} %, контраст ${value(zone.tone.contrast, 0)} %, гамма ${value(zone.tone.gamma, 2)}` : null]
    .filter(Boolean).join(' · ');
  /** Откуда точки зоны: с карты цветов или со сфотографированной фотогравировки (её вид, когда он другой, DEC-006). */
  const recipeFrom = (r) => (r.source === 'photo' && r.photo ? `по фото № ${r.photo.pair_id} (${kindName(r.photo.kind)})` : 'с карты цветов');
  const CHOICE = {drawing: 'рисунок сохранён', nearest: 'ближайший цвет', objects: 'раскраска по объектам'};
  /** Как подобраны серые зоны (0.23.0) — коротко, как у работы фотогравировки; у вида точками — ничего: точка бьёт на одной мощности. */
  const greysText = (zone) => (dotted(zone) ? '' : !zone.by_colour ? 'серые самой картинки'
    : [`серые подобраны под цвета: ${CHOICE[zone.colour_choice] || CHOICE.drawing}`, zone.contours ? 'контуры' : null,
      zone.rules && zone.rules.length ? `правил для частей: ${zone.rules.length}` : null].filter(Boolean).join(' · '));

  /** Измеренные шкалы серого лазера, линзы и титана работы, лучшие первыми: один запрос на работу (он долгий — грузится в фоне). */
  function scales(j) {
    const query = new URLSearchParams({device_id: j.device_id ?? '', material_id: j.material_id ?? ''});
    if (j.lens_id != null) query.set('lens_id', String(j.lens_id));
    const key = query.toString();
    if (!scalesCache.has(key)) scalesCache.set(key, get(`/grey-scales?${key}`).then((d) => d.scales || []));
    return scalesCache.get(key).catch((e) => { scalesCache.delete(key); throw e; });
  }

  /** Плитки «Вида» зоны: зона в каждом виде гравировки, один запрос на её состояние (адрес её картинки меняется с каждым изменением). */
  function kinds(j, zone) {
    const key = `${j.id}:${zone.number}:${zone.picture}`;
    if (!kindsCache.has(key)) kindsCache.set(key, get(`/vector/${j.id}/photo/${zone.number}/kinds`));
    return kindsCache.get(key).catch((e) => { kindsCache.delete(key); throw e; });
  }

  /** Полоса цветов шкалы по измеренным мощностям; у шкалы зоны её мощности (Min..Max или мощность точек) — ярко, остальное приглушено. */
  function bar(sc, zone) {
    const inside = (p) => (!zone ? true : dotted(zone) ? Math.abs(p - zone.dot_power) <= (sc.span[1] - sc.span[0]) / 40
      : p >= zone.min_power && p <= zone.max_power);
    return h('div', {class: 'vp-bar', role: 'img', 'aria-label': `Цвета шкалы от ${value(sc.span[0])} до ${value(sc.span[1])} %`},
      sc.bar.map((b) => h('span', {class: inside(b.power) ? '' : 'off', style: `background:${b.hex}`, title: `${value(b.power)} %`})));
  }

  /** Шкала — кнопка: полоса её цветов и её настройки; у выбранной полоса показывает мощности зоны. */
  const scaleButton = (sc, zone, chosen, choose) => h('button', {type: 'button', class: 'vp-scale-pick' + (chosen ? ' picked' : ''),
    'aria-pressed': chosen ? 'true' : 'false', onClick: chosen ? null : choose},
  bar(sc, chosen ? zone : null), h('span', {class: 'small'}, settingsText(sc.mode)),
  h('span', {class: 'small muted'}, `${stepText(sc.mode)} · ${value(sc.span[0])}–${value(sc.span[1])} %` + (sc.referenced ? '' : ' · без карты')));

  /** Вкладка «Фото». ctx: act(op) — одно действие редактора; select(ids) — выделить области; outline(ids) — обвести при наведении. */
  function create(j, ctx) {
    const list = h('div', {class: 'vp-zones'});
    const about = h('p', {class: 'small muted'});
    const el = h('div', {class: 'vw-ed-pane vp-pane'}, h('section', {class: 'vw-ed-section'}, h('h4', {}, 'Фотозоны'), about, list));
    let known = null, scalesError = null, rendering = 0;
    const opened = new Set();                        // zones whose list of other scales is open: it stays open after a change

    /** The zones' cards replace the old ones in one step, once the kinds of every zone have come: the panel keeps its place. */
    async function render() {
      const zones = j.zones || [], turn = ++rendering;
      const found = await Promise.all(zones.map((z) => (z.problem ? null : kinds(j, z).catch((e) => ({error: e.message})))));
      if (turn !== rendering) return;                                    // a newer state of the work came meanwhile
      fill(about, zones.length
        ? 'Области зоны гравируются фотогравировкой картинки работы, а не цветами: в файле — отдельный слой изображения после слоёв цвета, '
          + 'прозрачный вне зоны. Вид, шкала и мощности — у каждой зоны свои; всё отменяется (Ctrl+Z).'
        : 'Фотозон нет. Обведите мышью (лассо) области на картинке или щёлкните по ним (Shift+щелчок добавляет) и нажмите «Сделать фотозоной» '
          + 'в «Выделении» выше. Например, лицо: оно выйдет фотогравировкой, остальное — векторами.');
      fill(list, zones.map((zone, i) => card(zone, found[i])));
    }

    function card(zone, got) {
      const tiles = h('div', {class: 'vp-kinds', role: 'group', 'aria-label': `Вид гравировки фотозоны ${zone.number}`});
      const scaleBox = h('div', {class: 'vp-scale'});
      const box = h('article', {class: 'vp-zone' + (zone.problem ? ' bad' : '')},
        h('div', {class: 'row vp-head'}, h('strong', {}, `Фотозона ${zone.number}`), h('span', {class: 'spacer'}), open(zone),
          btn('Выделить', () => ctx.select(zone.regions)), btn('Вернуть в цвета', () => ctx.act({op: 'photo_delete', zone: zone.number}))),
        h('p', {class: 'small muted'}, `${zoneSummary(zone)} · ${value(zone.box.width)} × ${value(zone.box.height)} мм · ${area(zone.area_mm2)} · областей ${zone.regions.length}`),
        zone.problem ? h('p', {class: 'alert bad small'}, I18N.tr(zone.problem)) : null,
        h('h5', {}, 'Вид'), tiles,
        h('h5', {}, 'Шкала серого'), scaleBox,
        powers(zone),
        zone.estimate ? h('p', {class: 'small muted'}, 'Точки показаны оценкой по шкале: этот вид на этой мощности ещё не сфотографирован.') : null);
      box.addEventListener('mouseenter', () => ctx.outline(zone.regions));
      box.addEventListener('mouseleave', () => ctx.outline(null));
      fillKinds(tiles, zone, got);
      fillScale(scaleBox, zone);
      return box;
    }

    /** «Открыть»: зона на своём экране, как работа фотогравировки — подбор серых, контуры, шкала и прогноз рядом с картинкой. */
    function open(zone) {
      const b = btn('Открыть', () => go(`/vector-zone?work=${j.id}&zone=${zone.number}`), 'primary');
      b.setAttribute('title', 'Зона на своём экране, как фотогравировка: подбор серых, контуры, шкала, картинка рядом с прогнозом');
      return b;
    }

    function fillKinds(tiles, zone, got) {
      if (zone.problem) return fill(tiles, h('p', {class: 'small muted'}, 'Виды покажутся, когда шкала зоны будет измерена.'));
      if (got.error) return fill(tiles, h('p', {class: 'alert bad small'}, got.error));
      fill(tiles, got.kinds.map((k) => h('button', {type: 'button', class: 'vp-kind' + (k.key === zone.kind ? ' picked' : ''),
        'aria-pressed': k.key === zone.kind ? 'true' : 'false', title: PhotoModes.get(k.key) ? PhotoModes.get(k.key).controls : k.key,
        onClick: () => (k.key === zone.kind ? null : ctx.act({op: 'photo_set', zone: zone.number, kind: k.key}))},
      h('img', {src: k.picture, alt: '', loading: 'lazy'}), h('span', {}, kindName(k.key) + (k.estimate ? ' ≈' : '')))));
    }

    /** Шкала зоны и все измеренные шкалы лазера, линзы и титана работы: у каждой полоса её цветов, щелчок делает её шкалой зоны. */
    async function fillScale(scaleBox, zone) {
      const now = h('p', {class: 'small'}, `${settingsText(zone.scale)} · ${stepText(zone.scale)}`);
      if (!known && !scalesError) fill(scaleBox, now, h('p', {class: 'small muted'}, 'Загружаем измеренные шкалы…'));
      if (!known && !scalesError) {
        try { known = await scales(j); } catch (e) { scalesError = e.message; }
      }
      if (scalesError) return fill(scaleBox, now, h('p', {class: 'alert bad small'}, scalesError));
      const chosen = known.find((sc) => sameScale(sc.mode, zone.scale));
      const choose = (sc) => () => ctx.act({op: 'photo_set', zone: zone.number, scale: {material_id: sc.mode.material_id,
        global_passes: sc.mode.global_passes, ...Object.fromEntries(SCALE_KEYS.map((k) => [k, sc.mode[k]]))}});
      const others = known.filter((sc) => sc !== chosen);
      const list = others.length ? h('details', {class: 'vp-scales', open: !chosen || opened.has(zone.number)},
        h('summary', {class: 'small'}, `Другие шкалы этого лазера и титана: ${others.length}`),
        h('div', {class: 'vp-scale-list', role: 'group', 'aria-label': `Шкала серого фотозоны ${zone.number}`}, others.map((sc) => scaleButton(sc, zone, false, choose(sc)))))
        : null;
      if (list) list.addEventListener('toggle', () => (list.open ? opened.add(zone.number) : opened.delete(zone.number)));
      fill(scaleBox, chosen ? scaleButton(chosen, zone, true) : h('p', {class: 'alert warn small'}, `${settingsText(zone.scale)} · ${stepText(zone.scale)}: `
        + 'эта шкала больше не измерена — выберите другую'),
      zone.span ? h('p', {class: 'small muted'}, `Измерено при ширине зоны ${value(zone.width_mm)} мм: ${value(zone.span[0])}–${value(zone.span[1])} %.`) : null,
      list);
    }

    function powers(zone) {
      const number = (label, start, min, max) => h('input', {type: 'number', step: '0.1', min, max, value: start, 'aria-label': label});
      if (dotted(zone)) {
        const swatches = zone.dots ? h('span', {class: 'small muted'}, h('span', {class: 'sw', style: `background:${zone.dots.hex}`}), ' точка на ',
          h('span', {class: 'sw', style: `background:${zone.dots.clean_hex}`}), ' чистом титане') : null;
        const recipe = zone.dot_recipe;
        const toMap = btn(recipe ? 'Другой цвет' : 'Цвет с карты', () => go(DotPick.zoneAddress(j, zone.number, 'editor')), 'btn-small');
        toMap.setAttribute('title', `Открыть карту цветов и выбрать там любой измеренный цвет для точек фотозоны ${zone.number}: точки будут бить на настройках этого цвета`);
        if (recipe) {
          const back = btn('На шкалу', () => ctx.act({op: 'photo_set', zone: zone.number, dot_power: zone.dot_power}), 'btn-small');
          back.setAttribute('title', `Вернуть точки на шкалу зоны при ${value(zone.dot_power)} %`);
          return h('div', {class: 'vp-powers'},
            h('p', {class: 'small'}, `Точки ${recipeFrom(recipe)}: ${value(recipe.settings.power)} % · ${settingsText(recipe.settings)} · ${stepText(recipe.settings)}`),
            h('div', {class: 'row small'}, swatches, toMap, back),
            recipe.missing ? h('p', {class: 'alert warn small'}, 'Этого цвета больше нет среди измерений карты цветов: выберите другой или верните точки на шкалу.') : null,
            h('p', {class: 'small muted'}, 'Каждая точка бьёт на настройках этого цвета; тон — сколько точек. В файле Min = Max.'));
        }
        const power = number(`Мощность точек фотозоны ${zone.number}, %`, zone.dot_power, zone.span ? zone.span[0] : 0, zone.span ? zone.span[1] : 100);
        power.addEventListener('change', () => ctx.act({op: 'photo_set', zone: zone.number, dot_power: Number(power.value)}));
        return h('div', {class: 'vp-powers'}, h('label', {class: 'row small'}, h('span', {}, 'Мощность точек, %'), power), swatches,
          h('div', {class: 'row small'}, toMap, h('span', {class: 'muted'}, 'любой измеренный цвет этого лазера и титана')),
          h('p', {class: 'small muted'}, 'Каждая точка бьёт на этой мощности; тон — сколько точек. В файле Min = Max.'));
      }
      const low = number(`Min мощность фотозоны ${zone.number}, %`, zone.min_power, 0, 100);
      const high = number(`Max мощность фотозоны ${zone.number}, %`, zone.max_power, 0, 100);
      const send = () => ctx.act({op: 'photo_set', zone: zone.number, min_power: Number(low.value), max_power: Number(high.value)});
      low.addEventListener('change', send);
      high.addEventListener('change', send);
      const tone = h('input', {type: 'checkbox', checked: !!zone.by_colour, 'aria-label': `Цвета по картинке, фотозона ${zone.number}`});
      tone.addEventListener('change', () => ctx.act({op: 'photo_set', zone: zone.number, by_colour: tone.checked}));
      return h('div', {class: 'vp-powers'},
        h('div', {class: 'row small'}, h('label', {class: 'row'}, h('span', {}, 'Min, %'), low), h('label', {class: 'row'}, h('span', {}, 'Max, %'), high)),
        h('label', {class: 'row small'}, tone, h('span', {}, 'Цвета по картинке: серые подобраны так, чтобы цвета титана шли за цветами картинки, '
          + 'как у векторных областей вокруг. Выключено — гравируются серые самой картинки.')),
        zone.by_colour ? h('p', {class: 'small muted'}, `${greysText(zone)}. Как подбирать серые и контуры — в «Открыть».`) : null);
    }

    function update(next) { j = next; render(); }
    render();
    return {el, update};
  }

  return {create, zoneSummary, greysText, kindName};
})();
