/* Векторная работа из фотографии, вкладки «Цвета» и «AI» рабочего стола (REQ-042..REQ-049, REQ-050, DEC-001, DEC-075..DEC-077,
   DEC-084, DEC-085): каждому исходному цвету сразу дан измеренный цвет титана этого лазера, линзы и заготовки — самый быстрый
   в пределах допуска ΔE, иначе ближайший. Цвет дальше допуска помечен своим ΔE и обводится на картинке по запросу; файл он не
   блокирует. Цвета, снятые без привязки к эталону, автоматика не берёт, пока их не включить; вручную их выбрать можно.
   Вкладка «Цвета»: допуск и фильтры, автоматическая перекраска всей работы, варианты раскраски и подробная таблица цветов (в
   окне). Вкладка «AI»: стиль из списка или своё описание, переключатель свободной светлоты и разрешение отправить уменьшенное
   фото; без него AI видит только числа. Редактор (vector-editor.js) стоит в середине и справа, его собирает vector-workspace.js.
   Каждое действие возвращает работу целиком; вкладки обновляются на месте, редактор сохраняет масштаб, инструмент и выделение. */
'use strict';
const VectorColours = (() => {
  const {h, fill, btn, field, pill, fail, modal, facts, num, labText, agreed, CAUTION, steadiness, STEADY, originText, sourcesBlock} = App;
  const {chip, params, seconds, palette, de, duration, BASIS} = VectorEditor;
  const MODES = [['closest', 'Ближе к оригиналу'], ['tonality', 'Сохранить тональность'], ['contrast', 'Контраст соседей'], ['random', 'Случайно']];
  const MODE = {...Object.fromEntries(MODES), artistic: 'Художественно', fewer_layers: 'Меньше слоёв (прежний режим)', ai: 'AI'};   // the old mode only names variants saved with it
  /** Palette groups for «Художественно» (vector-detail I-6): the measured colours its hues are laid out from. */
  const SUBSETS = [['all', 'все цвета'], ['warm', 'тёплые'], ['cool', 'холодные'], ['bright', 'яркие']];
  const SUBSET = Object.fromEntries(SUBSETS);
  /** Стили AI-раскраски (DEC-084): ключ, название и что получится; «своё описание» — текст оператора. */
  const STYLES = [
    ['realistic', 'Реалистично', 'Как на фото, насколько позволяет палитра: близкие цвета, соседние области остаются различимыми.'],
    ['artistic', 'Артистично', 'Сюжет узнаётся, цвета как у художника: гармоничная гамма, тёплые света против холодных теней.'],
    ['impressionism', 'Импрессионизм', 'Свет и цвет важнее линий: тёплые света, цветные тени, без плоского чёрного.'],
    ['cubism', 'Кубизм', 'Плоские грани земляной гаммы, сильный контраст на каждой границе, даже если цвет уходит от натуры.'],
    ['custom', 'Своё описание', 'Опишите словами, какой вид нужен: AI следует описанию в пределах измеренных цветов.']];
  const STYLE = Object.fromEntries(STYLES.map(([id, name]) => [id, name]));
  const aiName = (ai) => 'AI · ' + (ai.style === 'custom' ? `«${(ai.text || '').slice(0, 40)}»` : STYLE[ai.style] || ai.style)
    + (ai.free_lightness ? ' · светлота свободна' : '') + (ai.photo ? ' · с фото' : '');
  const STATUS = {automatic: ['подобран автоматически', 'ok'], hand: ['выбран вручную', 'ok'], accepted: ['выбран вручную', 'ok'],
    missing: ['цвета титана больше нет среди измерений', 'bad'], excluded: ['не гравируется', '']};
  const HOW = {fastest_within_tolerance: 'самый быстрый в пределах допуска', nearest: 'ближайший', tonality: 'по тональности', random: 'случайно',
    contrast: 'отличается от соседей', artistic: 'художественно, светлота по порядку',
    cover: 'общий слой', nearest_outside_tolerance: 'ближайший, вне допуска', kept: 'выбор оператора', hand: 'выбор оператора', ai: 'выбор AI'};
  const stability = (e) => (e.stability && e.stability.assessed ? 'дисперсия ' + num(e.stability.variance) : 'не оценено');
  /** Уверенность в цвете настройки (REQ-045): число, сколько гравировок совпали и пометка, если автоматика цвет не берёт. */
  const confidence = (e) => h('span', {}, e.confidence == null ? 'не оценено' : num(e.confidence), h('div', {class: 'muted small'}, agreed(e.agreement)),
    e.caution ? pill(e.caution === 'superseded' ? 'заменён' : 'цвет менялся', 'bad') : null);

  const ORDERS = [['near', 'Ближайшие к исходному цвету'], ['stable', 'Самые стабильные'], ['fast', 'Самые быстрые']];
  const RANK = {stable: 2, single: 1, doubtful: 0};
  const trustOf = (e) => e.confidence ?? 1 / 3;                   // одна гравировка стоит столько же, сколько в agreement.SINGLE
  const BETTER = 6;                                               // сколько более стабильных цветов предложить взамен

  /** Выбор цвета титана из палитры (REQ-051): у каждого цвета видно, откуда он известен (тесты и работы) и насколько он стабилен; порядок и фильтр
      по повтору; взамен ненадёжного цвета предлагаются более стабильные, ближайшие к нему. Ближайшие к исходному цвету — первыми; снятые без
      привязки — с пунктиром. The colours are a short list (DEC-090): a line each with its square, ΔE and steadiness, pages of 30; the square
      chooses the colour, the line opens what it is and where it is known from. */
  const pick = (j, ...rest) => pickFrom(() => palette(j), ...rest);
  /** The same window over any list of measured colours (``load``: a promise of them), as the photo work's inscriptions need it. */
  async function pickFrom(load, title, sourceLab, current, onPick) {
    let entries;
    try { entries = await load(); } catch (e) { return fail(e); }
    const now = entries.find((e) => e.id === current) || null;
    let chosen = now;
    const near = (a, b) => de(a.lab, sourceLab) - de(b.lab, sourceLab);
    const compare = {near, fast: (a, b) => (a.time_s_per_cm2 ?? Infinity) - (b.time_s_per_cm2 ?? Infinity) || near(a, b),
      stable: (a, b) => RANK[steadiness(b)] - RANK[steadiness(a)] || trustOf(b) - trustOf(a) || near(a, b)};
    const better = h('div', {}), choice = h('p', {class: 'small'});
    const swatchOf = (e, text) => h('button', {type: 'button',
      class: `vw-swatch steady-${steadiness(e)}` + (e.basis === 'as-shot' ? ' as-shot' : '') + (e.automatic ? '' : ' not-auto') + (chosen && e.id === chosen.id ? ' picked' : ''),
      style: `background:rgb(${e.srgb.join(',')})`, 'data-entry': e.id, title: text, 'aria-label': text, onClick: () => choose(e)});
    const text = (e) => `${labText(e.lab)} · ΔE ${num(de(e.lab, sourceLab))} · ${STEADY[steadiness(e)][0]} · ${originText(e.sources)} · ${seconds(e.time_s_per_cm2)}`;
    const detail = (e) => h('div', {class: 'stack small'},
      h('div', {}, chip(e.srgb), ' ', labText(e.lab), ` · ΔE ${num(de(e.lab, sourceLab))} до исходного цвета`,
        now && now.id !== e.id ? ` · ΔE ${num(de(e.lab, now.lab))} до текущего` : ''),
      h('div', {}, pill(...STEADY[steadiness(e)]), ' ', `Уверенность ${e.confidence == null ? 'не оценена' : num(e.confidence)} · ${agreed(e.agreement)}`,
        e.caution ? [' ', pill(CAUTION[e.caution], 'warn')] : null),
      h('div', {class: 'muted'}, `${BASIS[e.basis] || ''} · гравировок ${e.engravings}, фото ${e.photographs} · ${seconds(e.time_s_per_cm2)}`),
      h('div', {class: 'muted'}, params(e.parameters)),
      e.automatic ? null : h('div', {class: 'muted'}, e.caution ? `Этот цвет автоматика не выбирает: ${CAUTION[e.caution]}; выбрать вручную можно.`
        : 'Этот цвет автоматика не выбирает (снят без привязки или медленнее предела времени); выбрать вручную можно.'),
      sourcesBlock(e.sources || [], e.agreement, e.lab, true),
      chosen && chosen.id === e.id ? null : h('div', {}, btn('Выбрать этот цвет', () => choose(e), 'btn-small')));
    const colours = App.list({items: entries, page: 30, key: (e) => String(e.id), open: now ? String(now.id) : null,
      row: (e) => [swatchOf(e, text(e)), h('span', {class: 'lst-text'}, `ΔE ${num(de(e.lab, sourceLab))} · ${STEADY[steadiness(e)][0]}`),
        h('span', {class: 'muted small'}, seconds(e.time_s_per_cm2))],
      details: detail, search: (e) => [labText(e.lab), originText(e.sources), ...(e.sources || []).map((s) => s.title)].join(' '),
      filters: [{key: 'steady', label: 'Повтор', options: [['stable', 'проверены повтором'], ['single', 'одна гравировка'], ['doubtful', 'сомнительные']],
        test: (e, v) => steadiness(e) === v}],
      sorts: ORDERS.map(([k, name]) => [k, name, compare[k]]), empty: 'Нет цветов под такой фильтр.'});
    function choose(e) { chosen = e; paint(); colours.refresh(); }
    function paint() {
      const stabler = now && steadiness(now) !== 'stable'
        ? entries.filter((e) => e.id !== now.id && steadiness(e) === 'stable').sort((a, b) => de(a.lab, now.lab) - de(b.lab, now.lab)).slice(0, BETTER) : [];
      fill(better, now && steadiness(now) !== 'stable' ? h('div', {class: 'stack small vw-better'},
        h('strong', {}, 'Стабильнее и похоже на текущий цвет'),
        stabler.length ? h('div', {class: 'vw-swatches'}, stabler.map((e) => swatchOf(e, `ΔE ${num(de(e.lab, now.lab))} до текущего · ${text(e)}`)))
          : h('span', {class: 'muted'}, 'Цветов, проверенных повтором, в палитре нет.')) : null);
      fill(choice, chosen ? ['Выбран: ', chip(chosen.srgb), ' ', labText(chosen.lab), ` · ΔE ${num(de(chosen.lab, sourceLab))} до исходного цвета · ${STEADY[steadiness(chosen)][0]}`]
        : h('span', {class: 'muted'}, 'Выберите цвет'));
    }
    paint();
    modal(title, h('div', {class: 'stack'},
      h('p', {class: 'muted small'}, `Все измеренные цвета этого лазера, линзы и титана этой марки (с любой плиты): ${entries.length}. Зелёная точка — цвет проверен повтором, красная — гравировки расходятся; `
        + 'у остальных одна гравировка. «Откуда» — из каких тестов и работ цвет известен. Квадрат выбирает цвет, строка открывает, откуда он известен.'),
      now ? h('p', {class: 'small'}, 'Сейчас: ', chip(now.srgb), ' ', pill(...STEADY[steadiness(now)]), ` ${originText(now.sources)}`) : null,
      better, colours.el, choice), [{label: 'Отмена', run: (m) => m.close()},
      {label: 'Применить', cls: 'primary', run: async (m) => { if (!chosen) return; m.close(); await onPick(chosen.id); }}]);
  }

  /** «Подробно по цветам» as a short list (DEC-090): a line per source colour — its colour and number, the titanium colour, how it was chosen,
      the recipe and ΔE, with the actions on the whole colour; how the titanium colour was measured, where it is known from, its confidence,
      stability and time open under the line. Pages of 30: every colour of a work is edited on one page. */
  function colourTable(run) {
    let j = null;
    const titanium = (c) => (c.entry_id == null ? null : j.entries[c.entry_id]);
    const list = App.list({id: 'vw.colour-table', items: [], page: 30, key: (c) => String(c.index),
      row: (c) => {
        const e = titanium(c), [label, kind] = STATUS[c.status] || [null, ''];
        return [chip(c.srgb, labText(c.lab)), h('strong', {}, `№ ${c.index + 1}`), '→', e ? chip(e.srgb, labText(e.lab)) : '—', label ? pill(label, kind) : null,
          h('span', {class: 'lst-text small'}, e ? params(e.parameters) : '—'),
          c.delta_e == null ? null : h('span', {}, `ΔE ${num(c.delta_e)}`), c.outside_tolerance ? pill('вне допуска', 'bad') : null,
          h('span', {class: 'muted small'}, `областей ${c.regions}`)];
      },
      actions: (c) => [btn('Изменить', () => pick(j, `Цвет группы № ${c.index + 1}`, c.lab, c.entry_id, (id) => run({op: 'set_colour', colour: c.index, entry_id: id}))),
        c.status === 'hand' || c.status === 'accepted' ? btn('Автоматически', () => run({op: 'set_colour', colour: c.index, entry_id: null})) : null,
        c.status === 'excluded' ? btn('Гравировать', () => run({op: 'include_colour', colour: c.index})) : btn('Не гравировать', () => run({op: 'exclude_colour', colour: c.index}))],
      details: (c) => {
        const e = titanium(c);
        return facts([['Исходный цвет', `${labText(c.lab)} · областей ${c.regions}`],
          ['Цвет титана', e ? h('span', {}, chip(e.srgb), ' ', labText(e.lab), c.how && HOW[c.how] ? ` · ${HOW[c.how]}` : '') : STATUS[c.status] ? STATUS[c.status][0] : '—'],
          ['Рецепт', e ? params(e.parameters) : null], ['Как измерен', e ? BASIS[e.basis] || '—' : null],
          ['Откуда', e ? `${originText(e.sources)} · фото ${e.photographs}` : null], ['Уверенность', e ? confidence(e) : null],
          ['Стабильность', e ? stability(e) : null], ['Время', e ? seconds(e.time_s_per_cm2) : null]]);
      },
      search: (c) => [`№ ${c.index + 1}`, titanium(c) ? params(titanium(c).parameters) : '', titanium(c) ? originText(titanium(c).sources) : ''].join(' '),
      filters: [VectorEditor.COLOUR_FILTER],
      sorts: [...VectorEditor.COLOUR_SORTS, ['fast', 'Быстрее', (a, b) => ((titanium(a) || {}).time_s_per_cm2 ?? Infinity) - ((titanium(b) || {}).time_s_per_cm2 ?? Infinity)
        || a.index - b.index]],
      empty: 'Нет исходных цветов под такой выбор.'});
    const el = h('div', {class: 'vw-wide stack'}, h('p', {class: 'muted small'}, 'Строка — исходный цвет и цвет титана, которым он будет выгравирован, его рецепт и ΔE. '
      + 'По щелчку на строке — как измерен цвет титана, откуда он известен, уверенность, стабильность и время.'), list.el);
    return {el, show(next) { j = next; list.items = j.colours; list.refresh(); }};
  }

  /** The colouring variants as a list (the tab is narrow); a variant of another split version cannot be restored until undo brings that
      version back. A short list
      (DEC-090): a line per variant — its number and way, mean ΔE and «текущий» or «Вернуть»; its totals open under the line; the newest first. */
  function variantList(run) {
    let j = null;
    const way = (v) => (v.mode === 'ai' && v.ai ? aiName(v.ai) : (MODE[v.mode] || '—') + (v.mode === 'artistic' ? ` · ${SUBSET[v.subset] || SUBSET.all}` : '')
      + (v.mode === 'random' || v.mode === 'artistic' ? ` (вариант ${v.seed})` : ''));
    // the server says whether a variant is restorable (a size change keeps the regions, DEC-002 of work-size-and-splitting-a-region-again);
    // a view without the flag goes by the split version
    const elsewhere = (v) => (v.restorable != null ? v.restorable === false : v.version != null && v.version !== j.document.version);
    const current = (v) => v.number === j.colouring.variant;
    const list = App.list({id: 'vw.variants', items: [], key: (v) => String(v.number), className: 'vw-variants',
      row: (v) => [h('strong', {class: 'lst-text'}, `№ ${v.number} · ${way(v)}`), h('span', {class: 'muted small'}, `ΔE ${num(v.totals.mean_delta_e)}`),
        current(v) ? pill('текущий', 'ok') : elsewhere(v) ? h('span', {class: 'muted small'}, `на разбиении № ${v.version}`) : null],
      actions: (v) => (current(v) || elsewhere(v) ? [] : [btn('Вернуть', () => run({op: 'restore', variant: v.number}))]),
      details: (v) => h('div', {class: 'stack small'},
        h('div', {}, `рецептов ${v.totals.recipes} · ΔE ${num(v.totals.mean_delta_e)} · в допуске ${v.totals.within_tolerance} из ${v.totals.colours} · `
          + (v.totals.seconds == null ? 'время не оценено' : duration(v.totals.seconds)) + ` · ${v.at.replace('T', ' ').slice(0, 16)}`),
        elsewhere(v) ? h('div', {class: 'muted'}, `На разбиении № ${v.version}: вернуть можно отменой.`) : null),
      search: (v) => `№ ${v.number} ${way(v)}`,
      sorts: [['new', 'Сначала новые', (a, b) => b.number - a.number],
        ['de', 'Меньше ΔE', (a, b) => (a.totals.mean_delta_e ?? Infinity) - (b.totals.mean_delta_e ?? Infinity) || b.number - a.number],
        ['fast', 'Быстрее', (a, b) => (a.totals.seconds ?? Infinity) - (b.totals.seconds ?? Infinity) || b.number - a.number]],
      empty: 'Вариантов пока нет'});
    return {el: list.el, show(next) { j = next; list.items = j.variants; list.refresh(); }};
  }

  /** «Художественно» (DEC-079): each press a new layout of hues from the chosen palette group; light places stay light. */
  function artisticRow(run) {
    const group = h('select', {'aria-label': 'Из каких цветов'}, SUBSETS.map(([v, name]) => h('option', {value: v}, name)));
    return h('div', {class: 'row'}, btn(MODE.artistic, () => run({op: 'assign', mode: 'artistic', subset: group.value}), 'btn-small'),
      h('label', {class: 'row small'}, 'из ', group),
      h('span', {class: 'muted small'}, 'новая раскладка оттенков при каждом нажатии, порядок светлоты как на оригинале'));
  }

  /** Раскраска с помощью AI: стиль, своё описание, свободная светлота, разрешение на фото и кнопка. Блок собирается один раз, поля не
      сбрасываются при обновлении карточки; update ставит то, что работа помнит (разрешение, ключ, текущая раскраска AI). */
  function aiBlock(j, run, permit) {
    const style = h('select', {'aria-label': 'Стиль AI-раскраски'}, STYLES.map(([v, name]) => h('option', {value: v}, name)));
    const hint = h('span', {class: 'small muted'});
    const text = h('input', {type: 'text', maxlength: String(j.ai.max_text), placeholder: 'например: как витраж, много синего', 'aria-label': 'Своё описание'});
    const own = field('Своё описание', text, `до ${j.ai.max_text} знаков`);
    const free = h('input', {type: 'checkbox'}), photo = h('input', {type: 'checkbox'});
    const off = h('p', {class: 'alert warn', hidden: true});
    const WHY = {key: 'AI-раскраска выключена: не задан ключ OpenAI (его вводят на экране «Сеть»). Остальные способы работают.',
      library: 'AI-раскраска выключена: на этом компьютере не установлена библиотека языковой модели. Установите зависимости приложения (команда в README), остальные способы работают.'};
    const current = h('p', {class: 'small'});
    let busy = false;
    const go = btn('Раскрасить с помощью AI', async (ev) => {
      const self = ev.currentTarget;
      busy = true; self.disabled = true; self.textContent = 'AI подбирает цвета…';
      try {
        await run({op: 'ai_colour', style: style.value, ...(style.value === 'custom' ? {text: text.value} : {}), free_lightness: free.checked});
      } finally { busy = false; self.textContent = 'Раскрасить с помощью AI'; sync(j); }
    }, 'primary');
    function sync(next) {
      j = next;
      fill(hint, (STYLES.find(([v]) => v === style.value) || STYLES[0])[2]);
      own.hidden = style.value !== 'custom';
      photo.checked = j.ai.photo_allowed;
      go.disabled = busy || !j.ai.available;
      off.hidden = j.ai.available;
      fill(off, WHY[j.ai.missing] || WHY.key);
      const now = j.colouring.mode === 'ai' && j.colouring.ai ? j.colouring.ai : null;
      fill(current, now ? ['Сейчас раскрашено AI: ', h('strong', {}, aiName(now).slice(5)), now.note ? ` — ${now.note}` : ''] : null);
      current.hidden = !now;
    }
    style.addEventListener('change', () => sync(j));
    photo.addEventListener('change', () => permit(photo.checked));
    sync(j);
    const el = h('div', {class: 'stack vw-ai'}, h('h4', {}, 'Раскраска с помощью AI'),
      h('div', {class: 'vw-split-fields'}, field('Стиль', style, null), own),
      hint,
      h('div', {class: 'vw-split-actions'},
        h('label', {class: 'row'}, free, h('span', {}, 'Свободная светлота: AI может менять порядок светлого и тёмного (по умолчанию он сохраняется)')),
        h('label', {class: 'row'}, photo, h('span', {}, `Разрешить отправить уменьшенное фото (до ${j.ai.photo_px} px) для этой работы`)), go),
      off, current,
      h('p', {class: 'muted small'}, 'AI подбирает измеренные цвета титана каждому цвету картинки по принципам выбранного стиля. Он получает только числа: цвета картинки (Lab) '
        + 'и их доли, какие цвета граничат и измеренные цвета титана; фото не видит, пока вы не разрешили. Цвета, выбранные вами вручную, остаются. '
        + 'Выбор AI сохраняется в варианте и при возврате к нему не пересчитывается.'));
    return {el, update: sync};
  }

  function settingsBar(j, run) {
    const s = j.settings;
    const tol = h('input', {type: 'number', step: 'any', min: '0', value: s.tolerance_de, 'aria-label': 'Допуск ΔE'});
    const maxTime = h('input', {type: 'number', step: 'any', min: '0', value: s.max_time ?? '', placeholder: 'без предела', 'aria-label': 'Наибольшее время, с/см²'});
    const asShot = h('input', {type: 'checkbox', checked: s.include_as_shot});
    return h('div', {class: 'toolbar'}, field('Допуск ΔE', tol), field('Наибольшее время, с/см²', maxTime),
      h('label', {class: 'row'}, asShot, h('span', {}, 'Включить цвета без привязки (сняты без эталона)')),
      btn('Применить', () => run({op: 'settings', tolerance_de: tol.value === '' ? null : +tol.value, max_time: maxTime.value === '' ? null : +maxTime.value,
        include_as_shot: asShot.checked})));
  }

  /** Части рабочего стола: вкладка «Цвета» (``colours``), вкладка «AI» (``ai``) и редактор (``editor``; его картинка и панель
      встают в рамку vector-workspace.js отдельно); update — на месте. */
  function parts(j, run, permit) {
    const editor = VectorEditor.create(j, run, {pick});
    const ai = aiBlock(j, run, permit);
    const intro = h('p', {class: 'muted small'}), empty = h('div', {}), bar = h('div', {});
    const detailed = colourTable(run), kept = variantList(run), rows = detailed.el;
    let settings = null;
    function show(next) {
      j = next;
      fill(intro, `Палитра: измеренных цветов ${j.palette_size}. Каждому исходному цвету дан самый быстрый цвет в пределах допуска ΔE, иначе ближайший; `
        + 'далёкие от оригинала можно обвести на картинке, файл они не блокируют.');
      fill(empty, j.palette_size ? null : h('div', {class: 'alert warn'}, 'Для этого лазера, линзы и титана этой марки нет измеренных цветов заливки: раскрасить нечем.'));
      const key = JSON.stringify(j.settings);
      if (key !== settings) { settings = key; fill(bar, settingsBar(j, run)); }       // поля не сбрасываются, пока настройки те же
      detailed.show(j);
      kept.show(j);
    }
    show(j);
    const colours = h('div', {class: 'stack vw-colours'}, intro, empty, bar,
      h('div', {class: 'vw-modes'}, h('span', {class: 'muted small'}, 'Перекрасить автоматически всю работу:'),
        h('div', {class: 'row'}, MODES.map(([mode, label]) => btn(label, () => run({op: 'assign', mode}), 'btn-small'))), artisticRow(run)),
      h('div', {class: 'row'}, btn('Подробно по цветам…', () => modal('Подробно по цветам', rows, [{label: 'Закрыть', run: (m) => m.close()}]))));
    const saved = h('div', {class: 'stack'}, h('h4', {}, 'Варианты раскраски'),
      h('p', {class: 'muted small'}, 'Каждая раскраска всей работы — автоматическая, от AI или после ваших правок — остаётся вариантом: к любому можно вернуться.'), kept.el);
    return {colours, variants: saved, ai: ai.el, editor, update(next) { show(next); ai.update(next); editor.update(next); }};
  }

  return {parts, pickFrom, styleName: (style) => STYLE[style] || style};
})();
