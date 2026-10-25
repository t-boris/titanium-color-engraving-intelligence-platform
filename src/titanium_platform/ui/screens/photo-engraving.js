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
  const {h, fill, btn, link, pill, get, post, del, form, field, go, toast, modal, confirmBox, duration, table, fail} = App;
  const {value, when, materialLabel, settingsText, modeQuery, GRAYSCALE, dotted, fromMap, firedSettings, kindName, hexChip, mm, mmList, scaleCard, newSlots, emptySlots,
    scaleDetail, sameScale, workPicture, colourTab, aiTab, kindTiles, kindChooser, KINDS_ABOUT} = PhotoPanels;
  let keys = null;                                     // клавиши открытой работы (Ctrl+Z, Ctrl+Shift+Z), как в редакторе векторной работы
  document.addEventListener('keydown', (ev) => { if (keys) keys(ev); });
  const PICTURES = 'image/png,image/jpeg,image/tiff,image/bmp,image/webp';
  const PREVIEW_GAP = 8;                     // px of white between the picture and its look in the preview (prediction.GAP)
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

  const DOT_WIDTH_ABOUT = 'Поправка ширины точки LightBurn (Dot Width Correction): точка лазера шире пикселя картинки, и без поправки '
    + 'картинка выходит темнее; LightBurn уменьшает каждую точку на эту ширину. Пишется в слой файла и в «Пробу этого вида»; тона вида, '
    + 'измеренные при одной ширине точки, к другой не подходят. Только в видах точками.';
  /** The dot width correction of a dot kind (0.28.0): a check box and the laser's dot width in mm, saved in the work by ``save({dot_width})``.
      A width turns the correction on, an empty field or a cleared box turns it off; a ticked box on an empty field waits for a width. In
      greyscale there is no correction: the field is hidden and the width waits in the work. */
  function dotWidthBox(save) {
    const on = h('input', {type: 'checkbox', 'aria-label': 'Поправка ширины точки'});
    const width = h('input', {type: 'number', min: '0.001', max: '0.2', step: '0.001', 'aria-label': 'Ширина точки лазера, мм'});
    const given = () => (width.value === '' ? null : Number(width.value));
    on.addEventListener('change', () => {
      if (!on.checked) save({dot_width: null});
      else if (given() != null) save({dot_width: given()});
    });
    width.addEventListener('change', () => { on.checked = given() != null; save({dot_width: given()}); });
    const el = h('label', {class: 'ge-power ge-dotwidth', title: DOT_WIDTH_ABOUT}, on, h('span', {class: 'small'}, 'Поправка ширины точки'), width,
      h('span', {class: 'small'}, 'мм'));
    function show(view) {
      el.hidden = !dotted(view) || !!view.problem;
      on.checked = view.dot_width != null;
      if (view.dot_width != null) width.value = String(view.dot_width);
    }
    return {el, show};
  }

  /** Работа на один экран: шкалы слева (выбранная — шкала работы), картинка и её прогноз посередине, вкладки справа. Изменения уходят на
      сервер по очереди, в том порядке, в каком сделаны, и показывается ответ на последнее; другая шкала приходит со своими Min и Max. */
  async function workScreen(id) {
    const [first, {scales}] = await Promise.all([get('/photo-works/' + id), get('/grey-scales')]);
    let view = first, detail = null, shownKey = null, seq = 0, queue = Promise.resolve();
    const error = h('p', {class: 'alert bad', role: 'alert', hidden: true});
    const list = h('div', {class: 'ge-scales'});
    const slots = newSlots();
    const base = `/photo-works/${id}`;
    // надписи: прогноз сервера уже рисует их врезанными, слой поверх прогноза — ручки и контур (inscriptions-in-works, REQ-005)
    let tab = null;
    const lettering = Lettering.create(view, {act: async (op) => !(await send(`${base}/texts`, op)), palette: () => get(`${base}/palette`),
      size: (v) => ({width: v.width_mm, height: v.height_mm}), drawn: false, open: () => tab === 'texts',
      pick: (title, lab, entryId, onPick) => VectorColours.pickFrom(() => get(`${base}/palette`), title, lab, entryId, onPick)});
    const picture = workPicture(save, () => kindChooser(base, view.kind || GRAYSCALE, (kind) => save({kind})),
      {ramp: `${base}/width-ramp`, variations: `${base}/variations`, original: `/api${base}/picture`, stage: (el, cols) => lettering.attach(el, cols, PREVIEW_GAP)});
    const head = workHead(view, step);
    // feature electron, REQ-085: a work pinned to a laboratory release shows its source under the head; a confirmed step brings the work anew
    const banner = LabSource.banner(base, 'photo', (next) => { view = next; shownKey = null; shown(); });
    const dotWidth = dotWidthBox(save);
    const ai = aiTab(base, save, (wish, fresh) => send(`${base}/ai`, {wish, fresh}));
    const colour = colourTab(base, save, (path, body) => send(path, body));
    const engraved = engravingsBlock(id);
    const tabs = App.tabs([['picture', 'Картинка', picture.details], ['colour', 'Раскраска', colour.el], ['ai', 'AI', ai.el], ['scale', 'Шкала', slots.scale],
      ['confirm', 'Подтверждение', h('div', {class: 'stack'}, engraved.el, slots.confirm)],
      ['points', 'Точки', slots.points], ['texts', 'Надписи', lettering.el]],
    {initial: 'picture', remember: 'ge.work.tab', label: 'Картинка и шкала', prefix: 'ge-tab', onSelect: (id) => { tab = id; lettering.opened(); }});
    const chosen = () => scales.find((sc) => sameScale(sc, view.scale)) || null;
    // at the work's width, for its kind and where its dots' colour comes from (the scale or a recipe of the colour map)
    const scaleKey = (v, mode = v.scale) => `${modeQuery(mode)}&row_mm=${v.width_mm}&kind=${v.kind || GRAYSCALE}&dots=${fromMap(v) ? v.dot_recipe.entry : ''}`;
    const cards = (current) => fill(list, scales.map((item) => scaleCard(item, item === current, () => pick(item))));

    function showScale() {
      if (detail) detail.stop();
      const sc = chosen();
      shownKey = scaleKey(view);
      cards(sc);
      engraved.load(view);
      const dot = dotted(view) && view.dot_power != null ? {power: view.dot_power, changed: (p) => save({dot_power: p}),
        recipe: fromMap(view) ? view.dot_recipe : null, hex: view.picture && view.picture.dots ? view.picture.dots.hex : null, dpi: view.dpi,
        map: () => go(DotPick.address(view))} : null;
      if (sc) detail = scaleDetail(sc, slots, {initial: [view.min_power, view.max_power], changed: (lo, hi) => save({min_power: lo, max_power: hi}), rowMm: view.width_mm, dot});
      else { detail = null; emptySlots(slots, 'Шкала этой работы не измерена: выберите шкалу слева.'); }
    }
    function shown() {
      head.update(view);
      banner.update(view);
      lettering.update(view);
      picture.show(view, chosen());
      dotWidth.show(view);
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
      if (document.querySelector('.modal-bg')) return;
      if (ev.key === 'Escape' && tab === 'texts' && lettering.escape()) return;
      if (t && (/^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName || '') || t.isContentEditable)) return;   // в поле ввода клавиши — его
      const z = ev.code === 'KeyZ' || (ev.key || '').toLowerCase() === 'z', y = ev.code === 'KeyY' || (ev.key || '').toLowerCase() === 'y';
      if ((ev.ctrlKey || ev.metaKey) && !ev.altKey && (z || y)) { ev.preventDefault(); step(z && !ev.shiftKey ? 'undo' : 'redo'); }
    };
    keys = key;
    return fill(root, head.el, banner.el, h('div', {class: 'os-body ge-body'},
      h('div', {class: 'os-col'}, h('div', {class: 'os-col-head'}, h('h3', {}, `Шкала работы (измерено ${scales.length})`)),
        h('div', {class: 'os-scroll'}, scales.length ? list : h('p', {class: 'muted'}, 'Измеренных шкал нет: выгравируйте пластину «Шкалы серого» и добавьте её фотографию.'))),
      h('div', {class: 'os-col ge-centre'}, h('div', {class: 'os-col-head'}, h('h3', {}, 'Картинка на шкале'), slots.title),
        h('div', {class: 'ge-work'}, picture.inputs, picture.tone, slots.powers, dotWidth.el, slots.error, error, slots.bar, picture.out, picture.foot)),
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
    // feature electron, REQ-085: the scales may come from a connected laboratory release; the own measurements are the default and a laboratory is
    // never chosen for the operator. With a release the own laser and lens the work is engraved with are asked, and the release's scale chosen.
    const source = LabSource.picker('photo', {onChange: switchSource});
    const own = h('div', {class: 'stack', hidden: true});
    const scaleSelect = h('select', {'aria-label': 'Шкала выпуска'});
    let pick = null, releaseScales = [];
    async function switchSource(src) {
      own.hidden = !src;
      releaseScales = [];
      if (!src) return;
      try {
        if (!pick) {
          pick = App.laserLensPicker(await App.hardwareLists());
          fill(own, h('div', {class: 'grid g2'}, field('Свой лазер', pick.laser, 'на нём гравируется работа'), field('Своя линза', pick.lens),
            field('Шкала выпуска', scaleSelect, 'первая — лучшая измеренная')));
        }
        const asked = JSON.stringify(src);
        const offered = await post('/labs/scales', src);
        if (asked !== JSON.stringify(source.value())) return;      // the source changed meanwhile
        releaseScales = offered.scales || [];
        fill(scaleSelect, releaseScales.map((sc, i) => h('option', {value: String(i)}, settingsText(sc.mode, sc.dpi) + (sc.span ? ` · ${value(sc.span[0], 1)}–${value(sc.span[1], 1)} %` : ''))));
        scaleSelect.disabled = !releaseScales.length;
        if (!releaseScales.length) fill(scaleSelect, h('option', {value: ''}, 'выпуск не измерил шкал серого с этой установкой'));
      } catch (e) { fail(e); }
    }
    const fields = h('div', {class: 'stack'}, App.filePick(fileIn, 'Выбрать картинку'), field('Название', name), field('Ширина на титане, мм', width), source.el, own,
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
        const src = source.value();
        if (src) {
          fd.append('source', JSON.stringify({...src, device_id: pick.deviceId(), lens_id: pick.lensId()}));
          const sc = releaseScales[+scaleSelect.value];
          if (sc) fd.append('scale', JSON.stringify(sc.mode));
        } else if (scale) fd.append('scale', JSON.stringify(scale));
        const made = await form('/photo-works', fd);
        m.close();
        kindStep(made.id);
      }}]);
    const kindStep = (id) => {
      let chosen = GRAYSCALE, kept = false, back = false;
      const label = () => `Создать в «${kindName(chosen)}»`;
      const tiles = kindTiles(`/photo-works/${id}`, chosen, (key) => { chosen = key; tiles.mark(key); create.textContent = label(); }, 'выбрано');
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
        h('p', {class: 'small'}, settingsText(firedSettings(w), w.dpi)),
        dotted(w) ? h('p', {class: 'small'}, `${materialLabel(w.material)} · ${kindName(w.kind)} · `
          + (fromMap(w) ? `точки ${value(w.dot_recipe.settings.power, 1)} % с карты цветов` : `точки ${value(w.dot_power, 1)} % (оценка по шкале)`))
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
