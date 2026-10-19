/* Векторная работа из фотографии, раздел «Цвета и разбиение» (REQ-042..REQ-049, DEC-001, DEC-075..DEC-077; разбиение входит в
   него, а не стоит отдельной карточкой — vector-detail-and-colour-control): каждому исходному цвету сразу
   дан измеренный цвет титана этого лазера, линзы и заготовки — самый быстрый в пределах допуска ΔE, иначе ближайший. Цвет
   дальше допуска помечен своим ΔE и обводится на картинке по запросу; файл он не блокирует. Цвета, снятые без привязки к
   эталону, автоматика не берёт, пока их не включить; вручную их выбрать можно. Раздел: настройки разбиения (блок split,
   его собирает vector.js), допуск и фильтры, автоматическая перекраска всей работы, редактор (vector-editor.js), подробная
   таблица цветов (раскрывается и прокручивается внутри карточки) и варианты раскраски. Каждое действие возвращает работу
   целиком; карточка обновляется на месте, редактор сохраняет масштаб, инструмент и выделение. */
'use strict';
const VectorColours = (() => {
  const {h, fill, btn, field, pill, fail, modal, table, num, labText} = App;
  const {chip, params, seconds, palette, de, BASIS} = VectorEditor;
  const MODES = [['closest', 'Ближе к оригиналу'], ['tonality', 'Сохранить тональность'], ['random', 'Случайно'], ['fewer_layers', 'Меньше слоёв']];
  const MODE = Object.fromEntries(MODES);
  const STATUS = {automatic: ['подобран автоматически', 'ok'], hand: ['выбран вручную', 'ok'], accepted: ['выбран вручную', 'ok'],
    missing: ['цвета титана больше нет среди измерений', 'bad'], excluded: ['исключён', '']};
  const HOW = {fastest_within_tolerance: 'самый быстрый в пределах допуска', nearest: 'ближайший', tonality: 'по тональности', random: 'случайно',
    cover: 'общий слой', nearest_outside_tolerance: 'ближайший, вне допуска', kept: 'выбор оператора', hand: 'выбор оператора'};
  const stability = (e) => (e.stability && e.stability.assessed ? 'дисперсия ' + num(e.stability.variance) : 'не оценено');

  /** Выбор цвета титана из палитры: ближайшие к исходному цвету первыми; снятые без привязки — с пунктиром. */
  async function pick(j, title, sourceLab, current, onPick) {
    let entries;
    try { entries = await palette(j); } catch (e) { return fail(e); }
    const sorted = [...entries].sort((a, b) => de(a.lab, sourceLab) - de(b.lab, sourceLab));
    let chosen = sorted.find((e) => e.id === current) || null;
    const detail = h('div', {class: 'small'});
    const show = () => fill(detail, chosen ? [chip(chosen.srgb), labText(chosen.lab), ` · ΔE ${num(de(chosen.lab, sourceLab))} · ${BASIS[chosen.basis] || ''} · `,
      `гравировок ${chosen.engravings}, фото ${chosen.photographs} · ${seconds(chosen.time_s_per_cm2)}`, h('div', {class: 'muted'}, params(chosen.parameters)),
      chosen.automatic ? null : h('div', {class: 'muted'}, 'Этот цвет автоматика не выбирает (снят без привязки или медленнее предела времени); выбрать вручную можно.')]
      : h('span', {class: 'muted'}, 'Выберите цвет'));
    const grid = h('div', {class: 'vw-swatches', role: 'group', 'aria-label': 'Измеренные цвета титана'}, sorted.map((e) => h('button', {type: 'button',
      class: 'vw-swatch' + (e.basis === 'as-shot' ? ' as-shot' : '') + (e.automatic ? '' : ' not-auto') + (e.id === current ? ' picked' : ''), style: `background:rgb(${e.srgb.join(',')})`,
      title: `${labText(e.lab)} · ΔE ${num(de(e.lab, sourceLab))} · ${seconds(e.time_s_per_cm2)}`, 'aria-label': `ΔE ${num(de(e.lab, sourceLab))}`,
      onClick: (ev) => { chosen = e; grid.querySelectorAll('.picked').forEach((x) => x.classList.remove('picked')); ev.target.classList.add('picked'); show(); }})));
    show();
    modal(title, h('div', {class: 'stack'}, h('p', {class: 'muted small'}, `Все измеренные цвета этого лазера, линзы и титана: ${entries.length}. Ближайшие к исходному цвету — первыми.`),
      grid, detail), [{label: 'Отмена', run: (m) => m.close()},
      {label: 'Применить', cls: 'primary', run: async (m) => { if (!chosen) return; m.close(); await onPick(chosen.id); }}]);
  }

  /** Подробная таблица: каждый исходный цвет с цветом титана, рецептом, данными и действиями над цветом целиком. */
  function colourRows(j, run) {
    return j.colours.map((c) => {
      const e = c.entry_id == null ? null : j.entries[c.entry_id];
      const [label, kind] = STATUS[c.status] || [null, ''];
      const actions = [btn('Изменить', () => pick(j, `Цвет группы № ${c.index + 1}`, c.lab, c.entry_id, (id) => run({op: 'set_colour', colour: c.index, entry_id: id})))];
      if (c.status === 'hand' || c.status === 'accepted') actions.push(btn('Автоматически', () => run({op: 'set_colour', colour: c.index, entry_id: null})));
      actions.push(c.status === 'excluded' ? btn('Вернуть', () => run({op: 'include_colour', colour: c.index})) : btn('Исключить', () => run({op: 'exclude_colour', colour: c.index})));
      return [h('span', {}, chip(c.srgb, labText(c.lab)), `№ ${c.index + 1}`, h('div', {class: 'muted small'}, `областей ${c.regions}`)),
        h('span', {}, e ? chip(e.srgb, labText(e.lab)) : '—', label ? pill(label, kind) : null, c.how && HOW[c.how] ? h('div', {class: 'muted small'}, HOW[c.how]) : null),
        e ? h('span', {class: 'small'}, params(e.parameters)) : '—', e ? BASIS[e.basis] || '—' : '—',
        e ? `${e.engravings} / ${e.photographs}` : '—', c.delta_e == null ? '—' : h('span', {}, num(c.delta_e), c.outside_tolerance ? [' ', pill('вне допуска', 'bad')] : null),
        e ? (e.confidence == null ? 'не оценено' : num(e.confidence)) : '—', e ? stability(e) : '—', e ? seconds(e.time_s_per_cm2) : '—',
        h('span', {class: 'row'}, actions)];
    });
  }

  /** Варианты раскраски; вариант другой версии разбиения сервер не вернёт, пока отмена не вернёт ту версию. */
  function variants(j, run) {
    const rows = [...j.variants].reverse().map((v) => {
      const elsewhere = v.version != null && v.version !== j.document.version;
      return [`№ ${v.number}`, (MODE[v.mode] || '—') + (v.mode === 'random' ? ` (вариант ${v.seed})` : ''),
        `${v.totals.recipes}`, num(v.totals.mean_delta_e), `${v.totals.within_tolerance} из ${v.totals.colours}`,
        v.totals.seconds == null ? 'не оценено' : Math.round(v.totals.seconds) + ' с', v.at.replace('T', ' ').slice(0, 16),
        v.number === j.colouring.variant ? pill('текущий', 'ok')
          : elsewhere ? h('span', {class: 'muted small'}, `сделан на разбиении № ${v.version}: вернуть его можно отменой`)
            : btn('Вернуть', () => run({op: 'restore', variant: v.number}))];
    });
    return table(['Вариант', 'Способ', 'Рецептов', 'Средний ΔE', 'Цветов в допуске', 'Время слоёв цвета', 'Когда', ''], rows, 'Вариантов пока нет');
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

  /** Раздел «Цвета и разбиение»: блок разбиения (``split``), допуск и фильтры, автоматическая перекраска, редактор, подробная
      таблица и варианты; update — на месте. */
  function card(j, run, split) {
    const editor = VectorEditor.create(j, run);
    const intro = h('p', {class: 'muted small'}), empty = h('div', {}), bar = h('div', {}), rows = h('div', {}), kept = h('div', {});
    const details = h('details', {class: 'vw-details'}, h('summary', {}, 'Подробно по цветам'), rows);
    let settings = null;
    function show(next) {
      j = next;
      fill(intro, `Палитра — все измеренные цвета этого лазера, линзы и титана (${j.palette_size}). Каждому исходному цвету сразу дан самый быстрый `
        + 'цвет в пределах допуска ΔE, а если такого нет — ближайший; его ΔE показан, далёкие от оригинала можно обвести на картинке. Файл они не блокируют.');
      fill(empty, j.palette_size ? null : h('div', {class: 'alert warn'}, 'Для этого лазера, линзы и титана нет измеренных цветов заливки: раскрасить нечем.'));
      const key = JSON.stringify(j.settings);
      if (key !== settings) { settings = key; fill(bar, settingsBar(j, run)); }       // поля не сбрасываются, пока настройки те же
      fill(rows, table(['Исходный цвет', 'Цвет титана', 'Рецепт', 'Как измерен', 'Гравировок / фото', 'ΔE', 'Уверенность', 'Стабильность', 'Время', ''], colourRows(j, run)));
      fill(kept, variants(j, run));
    }
    show(j);
    const el = h('div', {class: 'card stack vw-colours'}, h('h3', {}, '1. Цвета и разбиение'), split, h('h4', {}, 'Цвета'), intro, empty, bar,
      h('div', {class: 'row'}, h('span', {class: 'muted small'}, 'Перекрасить автоматически всю работу:'), MODES.map(([mode, label]) => btn(label, () => run({op: 'assign', mode})))),
      editor.el, details, h('h3', {}, 'Варианты раскраски'), kept);
    return {el, update(next) { show(next); editor.update(next); }};
  }

  return {card};
})();
