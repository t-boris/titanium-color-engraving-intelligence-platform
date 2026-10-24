/* Фотозона векторной работы на своём экране (0.23.0, DEC-116): то же, что работа фотогравировки (photo-engraving.js), теми же панелями
   (photo-panels.js) — шкалы слева, картинка зоны рядом с прогнозом посередине, вкладки справа; вид гравировки, Min и Max или мощность
   точек, подбор серых («Сохранить рисунок», «Ближайший цвет») и контуры. Картинка зоны — картинка работы в её областях, прозрачная вне их;
   ширина — по её областям (строки длиной с зону), шкалы — лазера, линзы и титана работы. Цвет точек вида точками — со шкалы или с карты
   цветов («Цвет с карты», 0.27.0, как у работы фотогравировки), яркость, контраст и гамма картинки — над ней. Каждое изменение — шаг
   редактора векторной работы: «Отменить» и «Повторить» (Ctrl+Z, Ctrl+Shift+Z) здесь — её; шаг, который убрал зону, возвращает к работе.
   Адрес: #/vector-zone?work=<id>&zone=<номер>; открывается кнопкой «Открыть» на карточке зоны во вкладке «Фото» редактора. */
'use strict';
(() => {
  const {h, fill, btn, get, post, go, toast} = App;
  const {value, GRAYSCALE, dotted, fromMap, firedSettings, kindName, settingsText, modeQuery, sameScale, scaleCard, newSlots, emptySlots, scaleDetail,
    workPicture, kindChooser} = PhotoPanels;
  let keys = null;                                     // клавиши открытой зоны (Ctrl+Z, Ctrl+Shift+Z) — отмена и повтор векторной работы
  document.addEventListener('keydown', (ev) => { if (keys) keys(ev); });

  /** Шапка: «← К работе», «Фотозона N» и что она такое, «Отменить» и «Повторить» векторной работы (``step('undo' | 'redo')``). */
  function zoneHead(first, step) {
    const title = h('div', {class: 'ge-title'});
    const undo = btn('Отменить', () => step('undo'), 'btn-small'), redo = btn('Повторить', () => step('redo'), 'btn-small');
    const el = h('div', {class: 'os-head'}, h('a', {class: 'btn btn-small', href: `#/vector?plan=${first.work.id}`}, '← К работе'), title,
      h('div', {class: 'row', role: 'group', 'aria-label': 'Отмена и повтор'}, undo, redo));
    function update(next) {
      undo.disabled = !(next.work.undo > 0);
      redo.disabled = !(next.work.redo > 0);
      undo.setAttribute('title', `Отменить (Ctrl+Z) — шаг векторной работы; шагов: ${next.work.undo}`);
      redo.setAttribute('title', `Повторить (Ctrl+Shift+Z) — шаг векторной работы; шагов: ${next.work.redo}`);
      fill(title, h('h2', {}, `Фотозона ${next.number}`),
        h('p', {class: 'sub'}, [`работа «${next.work.name}»`, next.name, `областей ${next.regions.length}`,
          `${value(next.box.width, 1)} × ${value(next.box.height, 1)} мм`].filter(Boolean).join(' · ')));
    }
    update(first);
    return {el, update};
  }

  /** Экран зоны. Изменения уходят на сервер по очереди, в том порядке, в каком сделаны, и показывается ответ на последнее; другая
      шкала приходит со своими Min и Max. */
  async function zoneScreen(work, number) {
    const base = `/vector/${work}/photo/${number}`;
    const first = await get(base);
    const query = new URLSearchParams({device_id: first.work.device_id, material_id: first.work.material_id ?? ''});
    if (first.work.lens_id != null) query.set('lens_id', String(first.work.lens_id));
    const {scales} = await get(`/grey-scales?${query}`);
    let view = first, detail = null, shownKey = null, seq = 0, queue = Promise.resolve(), left = false;
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const list = h('div', {class: 'ge-scales'});
    const slots = newSlots();
    /** Что сказать о слое зоны в файле работы. */
    const layer = (info) => (dotted(view)
      ? `Файл LightBurn работы: слой ${view.name} — изображение в режиме «${kindName(view.kind)}»: мощность ${value(info.dots.power, 1)} % (Min = Max — каждая точка `
        + `бьёт на ней), ${settingsText(firedSettings(view), info.dpi)}${fromMap(view) ? ' — настройки цвета с карты цветов' : ''}. `
        + 'Картинка работы — на месте зоны, вне её областей прозрачна: точки ставит LightBurn.'
      : `Файл LightBurn работы: слой ${view.name} — изображение в режиме градаций серого после слоёв цвета: Min ${value(info.power_range[0], 1)} %, `
        + `Max ${value(info.power_range[1], 1)} %, ${settingsText(view.scale, info.dpi)}. Картинка — на месте зоны, вне её областей прозрачна.`);
    const picture = workPicture(save, () => kindChooser(base, view.kind || GRAYSCALE, (kind) => save({kind})), {width: false, objects: false, layer});
    const head = zoneHead(view, step);
    const tabs = App.tabs([['picture', 'Картинка', picture.details], ['scale', 'Шкала', slots.scale], ['confirm', 'Подтверждение', slots.confirm],
      ['points', 'Точки', slots.points]], {initial: 'picture', remember: 'vz.zone.tab', label: 'Картинка и шкала', prefix: 'vz-tab'});
    const chosen = () => scales.find((sc) => sameScale(sc, view.scale)) || null;
    // at the zone's width, for its kind and where its dots' colour comes from (the scale or a recipe of the colour map)
    const scaleKey = (v, mode = v.scale) => `${modeQuery(mode)}&row_mm=${v.width_mm}&kind=${v.kind || GRAYSCALE}&dots=${fromMap(v) ? v.dot_recipe.entry : ''}`;
    const cards = (current) => fill(list, scales.map((item) => scaleCard(item, item === current, () => pick(item))));

    function showScale() {
      if (detail) detail.stop();
      const sc = chosen();
      shownKey = scaleKey(view);
      cards(sc);
      const dot = dotted(view) && view.dot_power != null ? {power: view.dot_power, changed: (p) => save({dot_power: p}),
        recipe: fromMap(view) ? view.dot_recipe : null, hex: view.picture && view.picture.dots ? view.picture.dots.hex : null, dpi: view.dpi,
        map: () => go(DotPick.zoneAddress(view.work, view.number))} : null;
      if (sc) detail = scaleDetail(sc, slots, {initial: [view.min_power, view.max_power], changed: (lo, hi) => save({min_power: lo, max_power: hi}), rowMm: view.width_mm, dot});
      else { detail = null; emptySlots(slots, 'Шкала этой зоны не измерена: выберите шкалу слева.'); }
    }
    function shown() {
      head.update(view);
      picture.show(view, chosen());
      if (scaleKey(view) !== shownKey) showScale();
    }
    /** Зоны больше нет (шаг отмены убрал её): обратно к работе. */
    function leave() {
      left = true;
      if (detail) detail.stop();
      toast('Фотозоны больше нет: шаг отмены убрал её. Открыта работа.', 'ok');
      go(`/vector?plan=${work}`);
    }
    /** One change of the zone (``path`` with ``body``): sent after those before it; the answer to the last one is shown. With ``again``
        the scale is shown anew from the answer (an undo or redo can bring back other Min and Max on the same scale). The promise gives the
        error of this change, or null. */
    function send(path, body, again = false) {
      if (left) return Promise.resolve(null);
      const mine = ++seq;
      error.hidden = true;
      picture.waiting();
      queue = queue.then(() => post(path, body)).then((next) => {
        if (next.gone) { leave(); return null; }
        view = next;
        if (mine === seq) { if (again) shownKey = null; shown(); }
        return null;
      }, (e) => { if (mine === seq) { error.textContent = e.message; error.hidden = false; shown(); } return e; });
      return queue;
    }
    function save(changes) { return send(`${base}/settings`, changes); }
    /** «Отменить» или «Повторить» (``kind``) — шаг векторной работы, которой принадлежит зона. */
    function step(kind) { return (view.work[kind] || 0) > 0 ? send(`${base}/${kind}`, {}, true) : Promise.resolve(null); }
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
      h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, `Шкала зоны (измерено ${scales.length})`)),
        h('div', {class: 'os-scroll'}, scales.length ? list : h('p', {class: 'muted'}, 'Шкал серого на этом лазере, линзе и титане нет: выгравируйте пластину «Шкалы серого» и добавьте её фотографию.'))),
      h('div', {class: 'os-col ge-centre'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Зона на шкале'), slots.title),
        h('div', {class: 'ge-work'}, picture.inputs, picture.tone, slots.powers, slots.error, error, slots.bar, picture.out, picture.foot)),
      h('div', {class: 'os-col ge-right'}, tabs.list, h('div', {class: 'os-scroll'}, tabs.panels))));
  }

  App.register({id: 'vector-zone', async render(ctx) {
    if (!ctx.query.work || !ctx.query.zone) { go('/vector'); return h('div'); }
    return zoneScreen(encodeURIComponent(ctx.query.work), encodeURIComponent(ctx.query.zone));
  }});
})();
