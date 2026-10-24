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
  const {h, fill, btn, field, pill, fail, modal, table, num, labText, agreed, CAUTION, steadiness, STEADY, originText, sourcesBlock} = App;
  const {chip, params, seconds, palette, de, duration, BASIS} = VectorEditor;
  const MODES = [['closest', 'Ближе к оригиналу'], ['tonality', 'Сохранить тональность'], ['contrast', 'Контраст соседей'], ['random', 'Случайно']];
  const MODE = {...Object.fromEntries(MODES), artistic: 'Художественно', fewer_layers: 'Меньше слоёв (прежний режим)', ai: 'AI'};   // the old mode only names variants saved with it
  /** Группы палитры для «Художественно» (vector-detail I-6): из каких измеренных цветов раскладываются оттенки. */
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
      привязки — с пунктиром. */
  async function pick(j, title, sourceLab, current, onPick) {
    let entries;
    try { entries = await palette(j); } catch (e) { return fail(e); }
    const now = entries.find((e) => e.id === current) || null;
    let chosen = now, order = 'near', repeatedOnly = false;
    const near = (a, b) => de(a.lab, sourceLab) - de(b.lab, sourceLab);
    const compare = {near, fast: (a, b) => (a.time_s_per_cm2 ?? Infinity) - (b.time_s_per_cm2 ?? Infinity) || near(a, b),
      stable: (a, b) => RANK[steadiness(b)] - RANK[steadiness(a)] || trustOf(b) - trustOf(a) || near(a, b)};
    const detail = h('div', {class: 'stack small'}), grid = h('div', {class: 'vw-swatches', role: 'group', 'aria-label': 'Измеренные цвета титана'}), better = h('div', {});
    const swatchOf = (e, text) => h('button', {type: 'button',
      class: `vw-swatch steady-${steadiness(e)}` + (e.basis === 'as-shot' ? ' as-shot' : '') + (e.automatic ? '' : ' not-auto') + (chosen && e.id === chosen.id ? ' picked' : ''),
      style: `background:rgb(${e.srgb.join(',')})`, 'data-entry': e.id, title: text, 'aria-label': text, onClick: () => { chosen = e; paint(); }});
    const text = (e) => `${labText(e.lab)} · ΔE ${num(de(e.lab, sourceLab))} · ${STEADY[steadiness(e)][0]} · ${originText(e.sources)} · ${seconds(e.time_s_per_cm2)}`;
    function paint() {
      const shown = entries.filter((e) => !repeatedOnly || steadiness(e) === 'stable').sort(compare[order]);
      fill(grid, shown.length ? shown.map((e) => swatchOf(e, text(e))) : h('p', {class: 'muted small'}, 'Нет цветов под такой фильтр.'));
      const stabler = now && steadiness(now) !== 'stable'
        ? entries.filter((e) => e.id !== now.id && steadiness(e) === 'stable').sort((a, b) => de(a.lab, now.lab) - de(b.lab, now.lab)).slice(0, BETTER) : [];
      fill(better, now && steadiness(now) !== 'stable' ? h('div', {class: 'stack small vw-better'},
        h('strong', {}, 'Стабильнее и похоже на текущий цвет'),
        stabler.length ? h('div', {class: 'vw-swatches'}, stabler.map((e) => swatchOf(e, `ΔE ${num(de(e.lab, now.lab))} до текущего · ${text(e)}`)))
          : h('span', {class: 'muted'}, 'Цветов, проверенных повтором, в палитре нет.')) : null);
      fill(detail, chosen ? [
        h('div', {}, chip(chosen.srgb), ' ', labText(chosen.lab), ` · ΔE ${num(de(chosen.lab, sourceLab))} до исходного цвета`,
          now && now.id !== chosen.id ? ` · ΔE ${num(de(chosen.lab, now.lab))} до текущего` : ''),
        h('div', {}, pill(...STEADY[steadiness(chosen)]), ' ', `Уверенность ${chosen.confidence == null ? 'не оценена' : num(chosen.confidence)} · ${agreed(chosen.agreement)}`,
          chosen.caution ? [' ', pill(CAUTION[chosen.caution], 'warn')] : null),
        h('div', {class: 'muted'}, `${BASIS[chosen.basis] || ''} · гравировок ${chosen.engravings}, фото ${chosen.photographs} · ${seconds(chosen.time_s_per_cm2)}`),
        h('div', {class: 'muted'}, params(chosen.parameters)),
        chosen.automatic ? null : h('div', {class: 'muted'}, chosen.caution ? `Этот цвет автоматика не выбирает: ${CAUTION[chosen.caution]}; выбрать вручную можно.`
          : 'Этот цвет автоматика не выбирает (снят без привязки или медленнее предела времени); выбрать вручную можно.'),
        sourcesBlock(chosen.sources || [], chosen.agreement, chosen.lab, true)]
        : h('span', {class: 'muted'}, 'Выберите цвет'));
    }
    const sorter = h('select', {'aria-label': 'Порядок цветов'}, ORDERS.map(([v, name]) => h('option', {value: v}, name)));
    sorter.addEventListener('change', () => { order = sorter.value; paint(); });
    const filter = h('input', {type: 'checkbox', 'aria-label': 'Только цвета, проверенные повтором'});
    filter.addEventListener('change', () => { repeatedOnly = filter.checked; paint(); });
    paint();
    modal(title, h('div', {class: 'stack'},
      h('p', {class: 'muted small'}, `Все измеренные цвета этого лазера, линзы и титана этой марки (с любой плиты): ${entries.length}. Зелёная точка — цвет проверен повтором, красная — гравировки расходятся; `
        + 'у остальных одна гравировка. «Откуда» — из каких тестов и работ цвет известен.'),
      now ? h('p', {class: 'small'}, 'Сейчас: ', chip(now.srgb), ' ', pill(...STEADY[steadiness(now)]), ` ${originText(now.sources)}`) : null,
      h('div', {class: 'row'}, h('label', {class: 'row small'}, 'Порядок ', sorter), h('label', {class: 'row small'}, filter, h('span', {}, 'Только проверенные повтором'))),
      better, grid, detail), [{label: 'Отмена', run: (m) => m.close()},
      {label: 'Применить', cls: 'primary', run: async (m) => { if (!chosen) return; m.close(); await onPick(chosen.id); }}]);
  }

  /** Подробная таблица: каждый исходный цвет с цветом титана, рецептом, данными и действиями над цветом целиком. */
  function colourRows(j, run) {
    return j.colours.map((c) => {
      const e = c.entry_id == null ? null : j.entries[c.entry_id];
      const [label, kind] = STATUS[c.status] || [null, ''];
      const actions = [btn('Изменить', () => pick(j, `Цвет группы № ${c.index + 1}`, c.lab, c.entry_id, (id) => run({op: 'set_colour', colour: c.index, entry_id: id})))];
      if (c.status === 'hand' || c.status === 'accepted') actions.push(btn('Автоматически', () => run({op: 'set_colour', colour: c.index, entry_id: null})));
      actions.push(c.status === 'excluded' ? btn('Гравировать', () => run({op: 'include_colour', colour: c.index})) : btn('Не гравировать', () => run({op: 'exclude_colour', colour: c.index})));
      return [h('span', {}, chip(c.srgb, labText(c.lab)), `№ ${c.index + 1}`, h('div', {class: 'muted small'}, `областей ${c.regions}`)),
        h('span', {}, e ? chip(e.srgb, labText(e.lab)) : '—', label ? pill(label, kind) : null, c.how && HOW[c.how] ? h('div', {class: 'muted small'}, HOW[c.how]) : null),
        e ? h('span', {class: 'small'}, params(e.parameters)) : '—', e ? BASIS[e.basis] || '—' : '—',
        e ? h('span', {}, originText(e.sources), h('div', {class: 'muted small'}, `фото ${e.photographs}`)) : '—', c.delta_e == null ? '—' : h('span', {}, num(c.delta_e), c.outside_tolerance ? [' ', pill('вне допуска', 'bad')] : null),
        e ? confidence(e) : '—', e ? stability(e) : '—', e ? seconds(e.time_s_per_cm2) : '—',
        h('span', {class: 'row'}, actions)];
    });
  }

  /** Варианты раскраски списком (вкладка узкая); вариант другой версии разбиения сервер не вернёт, пока отмена не вернёт ту версию. */
  function variants(j, run) {
    if (!j.variants.length) return h('p', {class: 'muted small'}, 'Вариантов пока нет');
    return h('div', {class: 'vw-variants'}, [...j.variants].reverse().map((v) => {
      const elsewhere = v.version != null && v.version !== j.document.version, current = v.number === j.colouring.variant;
      const way = v.mode === 'ai' && v.ai ? aiName(v.ai) : (MODE[v.mode] || '—') + (v.mode === 'artistic' ? ` · ${SUBSET[v.subset] || SUBSET.all}` : '')
        + (v.mode === 'random' || v.mode === 'artistic' ? ` (вариант ${v.seed})` : '');
      return h('div', {class: 'vw-variant' + (current ? ' current' : '')},
        h('div', {class: 'vw-variant-main'}, h('strong', {}, `№ ${v.number} · ${way}`),
          h('span', {class: 'small muted'}, `рецептов ${v.totals.recipes} · ΔE ${num(v.totals.mean_delta_e)} · в допуске ${v.totals.within_tolerance} из ${v.totals.colours} · `
            + (v.totals.seconds == null ? 'время не оценено' : duration(v.totals.seconds)) + ` · ${v.at.replace('T', ' ').slice(0, 16)}`)),
        current ? pill('текущий', 'ok')
          : elsewhere ? h('span', {class: 'muted small'}, `на разбиении № ${v.version}: вернуть можно отменой`)
            : btn('Вернуть', () => run({op: 'restore', variant: v.number})));
    }));
  }

  /** «Художественно» (DEC-079): каждый раз новая раскладка оттенков из выбранной группы палитры, светлые места остаются светлыми. */
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
    const WHY = {key: 'AI-раскраска выключена: не задан ключ языковой модели (переменная OPENAI_API_KEY или файл .env.local). Остальные способы работают.',
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
    const intro = h('p', {class: 'muted small'}), empty = h('div', {}), bar = h('div', {}), rows = h('div', {class: 'vw-wide'}), kept = h('div', {});
    let settings = null;
    function show(next) {
      j = next;
      fill(intro, `Палитра: измеренных цветов ${j.palette_size}. Каждому исходному цвету дан самый быстрый цвет в пределах допуска ΔE, иначе ближайший; `
        + 'далёкие от оригинала можно обвести на картинке, файл они не блокируют.');
      fill(empty, j.palette_size ? null : h('div', {class: 'alert warn'}, 'Для этого лазера, линзы и титана этой марки нет измеренных цветов заливки: раскрасить нечем.'));
      const key = JSON.stringify(j.settings);
      if (key !== settings) { settings = key; fill(bar, settingsBar(j, run)); }       // поля не сбрасываются, пока настройки те же
      fill(rows, table(['Исходный цвет', 'Цвет титана', 'Рецепт', 'Как измерен', 'Откуда', 'ΔE', 'Уверенность', 'Стабильность', 'Время', ''], colourRows(j, run)));
      fill(kept, variants(j, run));
    }
    show(j);
    const colours = h('div', {class: 'stack vw-colours'}, intro, empty, bar,
      h('div', {class: 'vw-modes'}, h('span', {class: 'muted small'}, 'Перекрасить автоматически всю работу:'),
        h('div', {class: 'row'}, MODES.map(([mode, label]) => btn(label, () => run({op: 'assign', mode}), 'btn-small'))), artisticRow(run)),
      h('div', {class: 'row'}, btn('Подробно по цветам…', () => modal('Подробно по цветам', rows, [{label: 'Закрыть', run: (m) => m.close()}]))));
    const saved = h('div', {class: 'stack'}, h('h4', {}, 'Варианты раскраски'),
      h('p', {class: 'muted small'}, 'Каждая раскраска всей работы — автоматическая, от AI или после ваших правок — остаётся вариантом: к любому можно вернуться.'), kept);
    return {colours, variants: saved, ai: ai.el, editor, update(next) { show(next); ai.update(next); editor.update(next); }};
  }

  return {parts, styleName: (style) => STYLE[style] || style};
})();
