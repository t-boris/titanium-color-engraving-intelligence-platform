/* Векторная работа: список сохранённых работ и рамка одной работы на один экран (REQ-053, REQ-054, DEC-085).
   Список (экран «Векторная работа» без работы): у каждой сохранённой работы миниатюра раскрашенной картинки, название, дата,
   размер, алгоритм, число цветов и слоёв, способ раскраски; кнопки «Открыть», «Сделать копию» (новая работа с тем же состоянием,
   старая остаётся) и «Удалить» с подтверждением. Рамка работы: шапка с названием и действиями, слева вкладки настроек, посередине
   картинка редактора, справа его панель; страница не прокручивается, прокручиваются только длинные списки внутри своей панели.
   Какая вкладка открыта, браузер помнит (удобство одного зрителя; App.tabs): после «Разбить заново» экран строится заново на той же вкладке.
   Карандаш рядом с названием (в списке, в шапке работы и на длинной странице других способов) открывает окно «Переименовать работу»: меняется
   только название, это не правка документа (REQ-055, DEC-086).
   «Размер…» рядом с размером в шапке (фича work-size-and-splitting-a-region-again, REQ-001): окно «Размер работы» с шириной и высотой в мм,
   связанными пропорциями картинки; разбиение не пересчитывается, а масштабируется — области, цвета, надписи и фотозоны остаются, шаг
   можно отменить. */
'use strict';
const VectorWorkspace = (() => {
  const {h, fill, btn, num, field, get, post, del, go, toast, fail, modal, confirmBox} = App;
  const MODE_NAME = {closest: 'Ближе к оригиналу', tonality: 'Сохранить тональность', random: 'Случайно', fewer_layers: 'Меньше слоёв (прежний режим)'};
  const STRATEGY_NAME = {photo: 'Фото: цветные области', fill: 'Заливка силуэта', text: 'Текст', line: 'Линии (центральные)', color: 'Цветные области (обводка)'};
  const TAB_KEY = 'vw.tab';
  const when = (iso) => (iso || '').replace('T', ' ').slice(0, 16);


  // ---- переименование ------------------------------------------------------------------------------------------------------------

  // the words of the dialog for what is renamed: a work (vector or photo engraving) or an experiment
  const WORDS = {work: {title: 'Переименовать работу', field: 'Название работы', blank: 'Впишите название работы', done: 'Работа переименована',
                        button: 'Переименовать работу'},
                 experiment: {title: 'Переименовать эксперимент', field: 'Название эксперимента', blank: 'Впишите название эксперимента',
                              done: 'Эксперимент переименован', button: 'Переименовать эксперимент'}};

  /** The dialog with the name in a field. A blank name is refused before any request, the name as it is closes the dialog without one,
      Enter saves (not while an input method is composing), and a second press while the first is being saved does nothing. ``base`` is
      the API of the kind of work (a photo engraving work is renamed at ``/photo-works``, an experiment at ``/experiments``). */
  function renameDialog(id, current, done, base, words) {
    let saving = false, box = null;
    const input = h('input', {value: current, autocomplete: 'off', 'aria-label': words.field,
      onKeydown: (ev) => { if (ev.key === 'Enter' && !ev.isComposing) { ev.preventDefault(); save(box.close).catch(fail); } }});
    async function save(close) {
      if (saving) return;
      const title = input.value.trim();
      if (!title) throw new Error(words.blank);
      if (title === current) { close(); return; }
      saving = true;
      try {
        const made = await post(`${base}/${encodeURIComponent(id)}/rename`, {name: title});
        toast(words.done, 'ok');
        close();
        done(made.name);
      } catch (e) { saving = false; throw e; }
    }
    box = modal(words.title, h('div', {class: 'stack'}, field('Название', input)), [
      {label: 'Отмена', run: (m) => m.close()}, {label: 'Сохранить', cls: 'primary', run: (m) => save(m.close)}]);
    if (input.select) input.select();
  }

  /** The pencil beside a work's name. ``renamed(name)`` is told the stored name once it is saved; the button keeps the name it shows,
      so its label and the dialog's field are right for the next rename too. ``kind`` is ``work`` or ``experiment`` (the words). */
  function renameButton(id, name, renamed, base = '/vector', kind = 'work') {
    let shown = name;
    const words = WORDS[kind];
    const label = () => `${words.button} «${shown}»`;
    const el = h('button', {type: 'button', class: 'btn btn-small vw-rename', title: 'Переименовать', 'aria-label': label(),
      onClick: () => renameDialog(id, shown, (stored) => { shown = stored; el.setAttribute('aria-label', label()); renamed(stored); }, base, words)}, '✎');
    return el;
  }

  // ---- список сохранённых работ --------------------------------------------------------------------------------------------------

  /** Способ раскраски одной строкой: ручной выбор и автоматические режимы названы так же, как в самой работе. */
  function colouringName(w) {
    if (w.mode === 'ai') return 'AI · ' + (w.ai_style === 'custom' ? `«${(w.ai_text || '').slice(0, 40)}»` : VectorColours.styleName(w.ai_style));
    return MODE_NAME[w.mode] || null;
  }

  function workCard(w) {
    const open = () => go('/vector?plan=' + w.id);
    const photo = w.strategy === 'photo';
    const how = colouringName(w);
    const copy = btn('Сделать копию', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/vector/${w.id}/copy`, {}); toast('Копия создана и открыта: старая работа осталась как была', 'ok'); go('/vector?plan=' + made.id); }
      catch (e) { fail(e); self.disabled = false; }
    }, 'btn-small');
    const remove = btn('Удалить', () => confirmBox(`Удалить работу «${w.name}»?`,
      'Исчезнут исходная картинка, разбиение и все варианты раскраски; вернуть работу будет нельзя. Чтобы сохранить её, сначала нажмите «Сделать копию».',
      'Удалить', async () => { await del('/plans/' + w.id); toast('Работа удалена', 'ok'); App.render(); }), 'danger btn-small');
    const thumb = h('a', {class: 'vw-thumb', href: '#/vector?plan=' + w.id, 'aria-label': 'Открыть работу ' + w.name},
      h('img', {src: `/api/vector/${w.id}/thumb.png?v=${encodeURIComponent(w.version + '-' + w.updated_at)}`, alt: '', loading: 'lazy'}));
    const title = h('h3', {}, w.name);
    const pencil = renameButton(w.id, w.name, (stored) => { w.name = stored; fill(title, stored); thumb.setAttribute('aria-label', 'Открыть работу ' + stored); });
    return h('article', {class: 'card vw-work-card'}, thumb,
      h('div', {class: 'stack vw-work-info'}, h('div', {class: 'vw-name-row'}, title, pencil),
        h('p', {class: 'small'}, `${num(w.width_mm, 1)} × ${num(w.height_mm, 1)} мм · ` + (photo ? VectorSplit.name(w.algorithm) : STRATEGY_NAME[w.strategy] || w.strategy)),
        photo ? h('p', {class: 'small'}, `цветов ${w.n_colours} · областей ${w.regions} · слоёв ${w.layers}` + (w.zones ? ` · фотозон ${w.zones}` : '')) : h('p', {class: 'small'}, `областей ${w.regions} · слоёв ${w.layers}`),
        h('p', {class: 'small'}, how ? `Раскраска: ${how}` : 'Ещё не раскрашена', w.variants ? ` · вариантов ${w.variants}` : ''),
        ...VectorReview.cardLines(w),
        h('p', {class: 'small muted'}, `изменена ${when(w.updated_at)}`),
        h('div', {class: 'row'}, btn('Открыть', open, 'primary btn-small'), copy, remove)));
  }

  /** Экран «Векторная работа» без работы: сохранённые работы и кнопка новой. */
  async function list() {
    const works = await get('/vector');
    const create = btn('Новая работа', () => go('/vector?new=1'), 'primary');
    return h('div', {class: 'stack'},
      h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Векторная работа'),
        h('p', {class: 'sub'}, 'Сохранённые работы: что выбрано и как выглядит, хранится на этом компьютере. Откройте работу, чтобы продолжить, или сделайте копию, чтобы переделать, не потеряв прежнюю.')),
        h('span', {class: 'spacer'}), create),
      works.length ? h('div', {class: 'vw-works'}, works.map(workCard))
        : h('div', {class: 'card empty'}, h('h3', {}, 'Работ пока нет'), h('p', {class: 'muted'}, 'Загрузите картинку: она разобьётся на цветные области, их можно раскрасить и выгрузить в LightBurn.'), create));
  }

  // ---- рамка одной работы --------------------------------------------------------------------------------------------------------

  // ---- размер работы ----------------------------------------------------------------------------------------------------------------

  const mm = (v) => String(Math.round(v * 10) / 10);           // a field's value: a dot, one decimal at most

  /** The dialog «Размер работы»: the width and the height in mm, linked by the picture's proportions; the side the operator typed last is
      what is sent (``resize({width_mm} | {height_mm})`` answers with the work, or null when the server refused and the error is shown).
      The size as it is closes the dialog without a request; Enter saves. */
  function sizeDialog(size, resize) {
    let saving = false, box = null, edited = 'width';
    const ratio = size.height / size.width;
    const onEnter = (ev) => { if (ev.key === 'Enter' && !ev.isComposing) { ev.preventDefault(); save(box.close).catch(fail); } };
    const width = h('input', {type: 'number', min: '1', step: '0.1', value: mm(size.width), 'aria-label': 'Ширина, мм', onKeydown: onEnter});
    const height = h('input', {type: 'number', min: '1', step: '0.1', value: mm(size.height), 'aria-label': 'Высота, мм', onKeydown: onEnter});
    width.addEventListener('input', () => { edited = 'width'; const w = parseFloat(width.value); height.value = w > 0 ? mm(w * ratio) : ''; });
    height.addEventListener('input', () => { edited = 'height'; const hh = parseFloat(height.value); width.value = hh > 0 ? mm(hh / ratio) : ''; });
    async function save(close) {
      if (saving) return;
      const value = parseFloat((edited === 'width' ? width : height).value);
      if (!(value > 0)) throw new Error('Впишите размер в миллиметрах: положительное число');
      if (Math.abs(value - size[edited]) < 0.05) { close(); return; }
      saving = true;
      try {
        const work = await resize(edited === 'width' ? {width_mm: value} : {height_mm: value});
        if (!work) { saving = false; return; }
        toast(`Размер работы теперь ${num(work.document.size_mm.width, 1)} × ${num(work.document.size_mm.height, 1)} мм; разбиение и цвета те же`, 'ok');
        close();
      } catch (e) { saving = false; throw e; }
    }
    box = modal('Размер работы', h('div', {class: 'stack'},
      h('p', {class: 'small muted'}, 'Одна сторона — ваше число, другая — по пропорциям картинки. Области, цвета, надписи и фотозоны остаются на своих '
        + 'местах, разбиение не пересчитывается; шаг можно отменить (Ctrl+Z).'),
      h('div', {class: 'toolbar'}, field('Ширина, мм', width), field('Высота, мм', height))), [
      {label: 'Отмена', run: (m) => m.close()}, {label: 'Изменить размер', cls: 'primary', run: (m) => save(m.close)}]);
    if (width.select) width.select();
  }

  /** Шапка работы: название и сводка, «Размер…» (только с ``actions.resize``), «Сделать копию», план гравировки и «Файл LightBurn»
      (открывает вкладку «Файл»). */
  function header(j, actions) {
    const title = h('div', {class: 'vw-work-title'});
    let current = j.document.size_mm;
    const size = actions.resize ? btn('Размер…', () => sizeDialog(current, actions.resize), 'btn-small vw-size') : null;
    const copy = btn('Сделать копию', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { const made = await post(`/vector/${j.id}/copy`, {}); toast('Копия создана и открыта: эта работа осталась как была', 'ok'); go('/vector?plan=' + made.id); }
      catch (e) { fail(e); self.disabled = false; }
    });
    const el = h('header', {class: 'vw-work-head'}, h('a', {class: 'btn btn-small', href: '#/vector'}, '← Мои работы'), title, h('span', {class: 'spacer'}),
      h('a', {class: 'btn btn-small', href: '#/plans/' + j.id}, 'План гравировки'), copy, btn('Файл LightBurn', actions.file, 'primary'));
    function update(next) {
      current = next.document.size_mm;
      const pencil = renameButton(next.id, next.name, (stored) => (actions.renamed ? actions.renamed(stored) : update({...next, name: stored})));
      fill(title, h('div', {class: 'vw-name-row'}, h('h2', {}, next.name), pencil),
        h('p', {class: 'sub'}, `${num(current.width, 1)} × ${num(current.height, 1)} мм`, size ? [' ', size] : null,
          ` · разбиение № ${next.document.version} · слоёв ${next.layers.length + (next.zones || []).length} из ${next.layer_cap}`
          + ((next.zones || []).length ? `, из них фотозон ${next.zones.length}` : '')));
    }
    update(j);
    return {el, update};
  }

  /** Три колонки в один экран: вкладки слева, картинка редактора посередине, его панель справа (``editor.el`` ложится в сетку
      обеими частями). */
  function frame({head, items, editor, initial}) {
    const box = App.tabs(items, {initial, remember: TAB_KEY, label: 'Разделы работы', prefix: 'vw-tab'});
    const left = h('aside', {class: 'vw-left', 'aria-label': 'Настройки работы'}, box.list, h('div', {class: 'vw-panels'}, box.panels));
    return {el: h('div', {class: 'vw-work workspace'}, head, h('div', {class: 'vw-work-body'}, left, editor.el)), select: box.select};
  }

  return {list, header, frame, renameButton};
})();
