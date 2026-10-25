/* Что лаборатория знает о фотогравировке (photo-engraving-quality REQ-003..REQ-005, DEC-001..DEC-006): выводы по каждой сфотографированной
   фотогравировке (тон, детали и что поменять), копии одной платы рядом и следующая плата, лучшие измеренные настройки вида, шаг
   «темнее / светлее / чётче / мягче» и опыт, который предлагает лаборатория. Всё считает сервер (photo_quality.py, photo_knowledge.py);
   здесь — только тексты по-русски. */
'use strict';
const PhotoQuality = (() => {
  const {h, fill, btn, pill, get, post} = App;
  // toast, go and fail join App later (dialogs.js, router.js): taken when used
  const made = (plate) => { App.toast(`Создано: ${plate.name}`, 'ok'); App.go('/experiment/plan-' + plate.plan_id); };
  const value = (v, d = 2) => (v == null ? '—' : String(+(+v).toFixed(d)).replace('.', ','));
  const signed = (v, d = 1) => (v > 0 ? '+' : v < 0 ? '−' : '') + value(Math.abs(v), d);
  const pct = (share) => `${value(share * 100, 0)} %`;
  const copiesOf = (n) => `${n} ${n % 10 === 1 && n % 100 !== 11 ? 'копия' : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 12 || n % 100 > 14) ? 'копии' : 'копий'}`;
  const SETTING = {power: 'мощность', min_power: 'Min', speed: 'скорость', frequency: 'частота', pulse_width: 'длительность импульса',
    line_interval: 'шаг строк', dot_width: 'поправка ширины точки', dither: 'вид', passes: 'проходы', global_passes: 'глобальные проходы'};
  const UNIT = {power: ' %', min_power: ' %', speed: ' мм/с', frequency: ' кГц', pulse_width: ' нс', line_interval: ' мм', dot_width: ' мм'};
  const DIGITS = {power: 1, min_power: 1, speed: 0, frequency: 0, pulse_width: 0, line_interval: 4, dot_width: 3};
  /** Значение настройки с единицей; поправка ширины точки без значения — выключена. */
  const setting = (key, v) => (key === 'dither' ? PhotoModes.label(v) : v == null ? (key === 'dot_width' ? 'выкл.' : '—') : value(v, DIGITS[key] ?? 2) + (UNIT[key] || ''));
  const changeText = (c) => `${SETTING[c.setting] || c.setting} ${setting(c.setting, c.from)} → ${setting(c.setting, c.to)}`;
  /** Откуда точки рецепта работы или фотозоны (BUG-008): заливка карты цветов или сфотографированная фотогравировка (``source`` "photo") —
      её фото и вид; «оценка», когда на этих настройках её не фотографировали (``basis`` "estimate"). */
  const fromPhoto = (r) => !!r && r.source === 'photo';
  const recipeFrom = (r) => (!fromPhoto(r) ? 'с карты цветов' : !r.photo ? 'по оценке'
    : `${r.basis === 'estimate' ? 'оценка по фото' : 'по фото'} № ${r.photo.pair_id} (${PhotoModes.label(r.photo.kind)})`);
  /** Что обычно исправляет вывод: настройка и куда её двигать (``PRIOR_MOVES``). */
  const moveText = (m) => (m.setting === 'dither' ? `вид → ${PhotoModes.label(m.to)}` : `${SETTING[m.setting] || m.setting} ${m.direction === 'up' ? 'больше' : 'меньше'}`);
  const FINDING = {
    good: (f) => [`Тон в порядке (оценка ${value(f.value, 2)})`, 'ok'],
    flat: (f) => [`Мало контраста: от чёрного до белого всего ${value(f.value, 0)} L*`, 'warn'],
    reversed: (f) => [`Тон разворачивается: на ${f.value.length} ${f.value.length === 1 ? 'ступени' : 'ступенях'} более тёмный серый вышел светлее`, 'bad'],
    shadows_blocked: (f) => [`Тени слились: всё темнее ${pct(f.value)} серого выходит одним тоном`, 'warn'],
    highlights_lost: (f) => [`Света пропали: всё светлее ${pct(f.value)} серого выходит одним тоном`, 'warn'],
    midtones_dark: () => ['Полутона темнее картинки', 'warn'],
    midtones_light: () => ['Полутона светлее картинки', 'warn'],
    detail_lost: (f) => [`Детали размыты: мелкие (0,4 мм) сохранились на ${pct(f.value)}`, 'warn'],
    grainy: (f) => [`Зернисто: пятна ±${value(f.value, 1)} L* там, где картинка ровная`, 'warn'],
  };
  /** Один вывод: что не так и что обычно поправляет (по опыту процесса, пока платы его не измерят). */
  function findingLine(f) {
    const [text, tone] = (FINDING[f.code] || (() => [f.code, 'warn']))(f);
    return h('li', {}, pill(text, tone), f.moves && f.moves.length
      ? h('span', {class: 'small'}, ` Что поменять: ${f.moves.map(moveText).join(', ')}`, h('span', {class: 'muted'}, f.basis === 'prior' ? ' (по опыту процесса)' : ''))
      : f.code === 'reversed' ? h('span', {class: 'small muted'}, ' Точки одной мощности сами не разворачиваются: сначала посмотрите на фото — блики, пыль, рамка.') : null);
  }
  /** Тон и детали одной фотогравировки в цифрах. */
  function toneText(q) {
    const t = q.tone;
    const d = q.detail;
    const scales = d && (d.scales || []).filter((x) => x.kept != null);
    const detail = !d ? '' : scales && scales.length > 1
      ? ` Детали сохранились: ${scales.map((x) => `${value(x.mm, 1)} мм — ${pct(x.kept)}`).join(', ')}${d.grain_L != null ? `; зерно ±${value(d.grain_L, 1)} L*` : ''}.`
      : d.kept != null ? ` Мелкие детали (0,4 мм) сохранились на ${pct(d.kept)}${d.grain_L != null ? `, зерно ±${value(d.grain_L, 1)} L*` : ''}.` : '';
    return `Различимых тонов ${t.levels} из ${t.steps}, от чёрного до белого ${value(t.range_L, 0)} L* (${value(t.black_L, 0)} → ${value(t.white_L, 0)}), `
      + `в среднем L* ${value(t.mean_L, 0)}.${detail}`;
  }

  /** Выводы по слою проверки (``rep.photo_quality``): оценка, тон и детали, что не так и что поменять. */
  function layerBox(name, q) {
    if (!q) return null;
    return h('div', {class: 'stack pq-layer'},
      h('div', {class: 'row'}, h('strong', {}, I18N.name(name)), pill(`оценка ${value(q.score, 2)}`, q.score >= 0.7 ? 'ok' : q.score >= 0.4 ? 'warn' : 'bad'),
        h('span', {class: 'muted small'}, q.tone.measured_by === 'grey ramp' ? 'по полоске серого' : 'по картинке')),
      h('p', {class: 'small'}, toneText(q)),
      h('ul', {class: 'small pq-findings'}, q.findings.map(findingLine)));
  }

  /** Что сделало одно изменение копии против первой: светлее или темнее, тени, света, тоны, детали. */
  function effectText(e) {
    const parts = [];
    if (e.mean_L != null && Math.abs(e.mean_L) >= 0.5) parts.push(e.mean_L > 0 ? `светлее на ${value(e.mean_L, 1)} L*` : `темнее на ${value(-e.mean_L, 1)} L*`);
    if (e.range_L != null && Math.abs(e.range_L) >= 1) parts.push(`контраст ${signed(e.range_L, 0)} L*`);
    if (e.shadows_blocked != null && Math.abs(e.shadows_blocked) >= 0.05) parts.push(e.shadows_blocked < 0 ? `тени открылись на ${pct(-e.shadows_blocked)}` : `тени слились ещё на ${pct(e.shadows_blocked)}`);
    if (e.highlights_lost != null && Math.abs(e.highlights_lost) >= 0.05) parts.push(e.highlights_lost < 0 ? `света вернулись на ${pct(-e.highlights_lost)}` : `света пропали ещё на ${pct(e.highlights_lost)}`);
    if (e.levels) parts.push(`тонов ${signed(e.levels, 0)}`);
    if (e.kept != null && Math.abs(e.kept) >= 0.03) parts.push(e.kept > 0 ? `чётче (+${pct(e.kept)} деталей)` : `мягче (−${pct(-e.kept)} деталей)`);
    return parts.length ? parts.join(', ') : 'почти без разницы';
  }

  /** Копии платы «Подобрать настройки» рядом (``pair.variations``): какая лучше, что сделало каждое изменение и следующая плата. */
  function variationsBox(v, pairId, accepted) {
    if (!v) return null;
    const best = v.ranked[0];
    const next = v.next ? btn('Сделать следующую плату', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      try { made(await post(`/pairs/${pairId}/next-variations`, {})); } catch (e) { App.fail(e); self.disabled = false; }
    }, 'primary btn-small') : null;
    if (next && !accepted) { next.disabled = true; next.setAttribute('title', 'Сначала примите проверку: следующая плата строится вокруг лучшей копии'); }
    return h('div', {class: 'stack pq-variations'},
      h('h3', {}, 'Копии рядом'),
      h('p', {}, h('strong', {}, `Лучше всех — копия ${v.best_label}`), ` (оценка ${value(best.score, 2)}${v.best === 1 ? ': настройки работы и так лучшие' : ''}).`),
      h('ol', {class: 'small'}, v.ranked.map((c) => h('li', {}, `${c.label} — ${value(c.score, 2)}`,
        c.findings.length && c.findings[0].code !== 'good' ? h('span', {class: 'muted'}, ' · ' + c.findings.map((f) => (FINDING[f.code] ? FINDING[f.code](f)[0] : f.code)).join('; ')) : null))),
      v.effects.length ? h('div', {class: 'stack'}, h('h4', {}, 'Что сделало каждое изменение (против копии 1)'),
        h('ul', {class: 'small'}, v.effects.map((e) => h('li', {}, h('strong', {}, e.changed.map(changeText).join(', ') || e.label), ': ', effectText(e))))) : null,
      v.settled ? h('p', {class: 'alert ok small'}, 'Поиск сошёлся: первая копия осталась лучшей и при малых изменениях. Это лучшие настройки этого вида для этой картинки.')
        : h('p', {class: 'small'}, next, ` Следующая плата: та же картинка вокруг копии ${v.best}, изменения вдвое меньше (шаг ${value(v.next.step, 3)} от первых). `
          + 'С каждой платой настройки ближе к лучшим.'));
  }

  const DIRECTION = {darker: 'Темнее', lighter: 'Светлее', sharper: 'Чётче', softer: 'Мягче'};
  /** Что делает настройка (измерено): на сколько темнее или светлее и чётче на удвоение (поправка точки — на 0,01 мм). */
  function effectLine(key, e) {
    const per = e.per === 'doubling' ? 'вдвое больше' : '+0,01 мм';
    const parts = [];
    if (e.mean_L) parts.push(e.mean_L.median > 0 ? `светлее на ${value(e.mean_L.median, 1)} L*` : `темнее на ${value(-e.mean_L.median, 1)} L*`);
    if (e.kept) parts.push(e.kept.median > 0 ? `детали +${pct(e.kept.median)}` : `детали −${pct(-e.kept.median)}`);
    if (e.score) parts.push(`оценка ${signed(e.score.median, 2)}`);
    return h('li', {}, `${SETTING[key] || key} ${per}: ${parts.join(', ') || 'без заметной разницы'}`,
      h('span', {class: 'muted'}, ` (по фото ${e.photographs.map((p) => '№' + p).join(', ')})`));
  }
  function stepButton(direction, step, apply) {
    const b = btn(DIRECTION[direction], () => apply(step.apply), 'btn-small');
    if (step.refused) { b.disabled = true; b.setAttribute('title', I18N.tr(step.refused)); return b; }
    const how = step.basis === 'measured' ? `измерено по фото ${step.evidence.photographs.map((p) => '№' + p).join(', ')}` : 'по опыту процесса: ещё не измерено';
    b.setAttribute('title', `${step.changed.map(changeText).join(', ')} — ${how}`);
    return b;
  }
  /** Что изменит «Взять …»: шкала, Min и Max или настройки точек. */
  const takeText = (t) => (t.dot_settings ? `Точки: ${setting('power', t.dot_settings.power)}, ${setting('speed', t.dot_settings.speed)}, `
    + `шаг ${setting('line_interval', t.dot_settings.line_interval)}${'dot_width' in t ? `, поправка точки ${setting('dot_width', t.dot_width)}` : ''}.`
    : `${t.scale ? `Шкала ${setting('speed', t.scale.speed)}, шаг ${setting('line_interval', t.scale.line_interval)}; ` : ''}`
      + `Min ${setting('min_power', t.min_power)}, Max ${setting('power', t.max_power)}.`);
  /** Что найдёт предложенная плата и какого она размера (``proposal.copies``, ``proposal.plate``). */
  function proposalText(p) {
    const changes = p.copies.slice(1).map((c) => c.map(changeText).join(', ')).join('; ');
    const size = p.plate ? ` Плата ${value(p.plate.size_mm[0], 0)} × ${value(p.plate.size_mm[1], 0)} мм: ${copiesOf(p.copies.length)} по `
      + `${value(p.plate.copy_mm[0], 1)} × ${value(p.plate.copy_mm[1], 1)} мм, под каждой полоска серого.`
      : ' Картинки для платы ещё нет: сделайте первую плату из фотоработы или фотозоны («Подобрать настройки: 8 копий»).';
    return `Копия 1 — центр, остальные меняют по одной настройке: ${changes}; по фото станет видно, какая лучше.${size}`;
  }
  const STATUS = {settled: ['поиск сошёлся', 'ok'], searching: ['поиск идёт', 'warn'], measured: ['измерено, но не подобрано', 'warn'], unmeasured: ['не измерено', 'warn'],
    failed: ['не получился', 'bad']};
  /** Почему гравировка не стала лучшей (``failed``, DEC-006): картинки не видно или она вышла негативом. */
  const failedWhy = (e) => (e.tone.range_L <= 0
    ? `${e.settings.dither === 'grayscale' ? 'тёмные места не темнее светлых' : `точки не темнее титана (L* ${value(e.black_lab[0], 0)})`}: картинки не видно или она вышла негативом`
    : `картинка едва видна: тёмное темнее светлого всего на ${value(e.tone.range_L, 0)} L*`);
  /** Гравировки вида на этом титане, где картинки не вышло, самые новые первыми. */
  const failedText = (name, failed) => `«${name}» на этом титане не получился: `
    + failed.slice(0, 3).map((e) => `фото № ${e.source.pair_id}, ${setting('power', e.settings.power)} — ${failedWhy(e)}`).join('; ')
    + (failed.length > 3 ? `; ещё ${failed.length - 3}` : '') + '.';

  /** «Что знает лаборатория» у работы или фотозоны: лучшие измеренные настройки её вида, что делает каждая настройка, шаги «Темнее»,
      «Светлее», «Чётче», «Мягче» (``apply(changes)`` сохраняет изменение) и опыт, который закрывает незнание. ``path`` — адрес владельца
      (``/photo-works/<id>`` или ``/vector/<id>/photo/<n>``); ``load(view)`` перечитывает подсказку, когда меняется то, что гравируется. */
  function advisor(path, apply) {
    const el = h('div', {class: 'stack pq-advisor'});
    let shown = null;
    async function load(view) {
      const key = JSON.stringify([view.kind, view.scale, view.min_power, view.max_power, view.dot_power, view.dot_width,
        view.dot_recipe && view.dot_recipe.settings]);
      if (key === shown) return;
      shown = key;
      fill(el, h('p', {class: 'muted small'}, 'Читаем, что известно о виде…'));
      let a;
      try { a = await get(`${path}/advice`); } catch (e) { if (shown === key) fill(el, h('p', {class: 'alert warn small'}, I18N.tr(e.message))); return; }
      if (shown !== key) return;
      const name = PhotoModes.label(a.kind);
      const b = a.best;
      const failed = a.failed || [];
      const status = STATUS[a.status];
      const proposal = a.proposal && (a.proposal.kind === 'next' || a.proposal.plate) ? btn(a.proposal.kind === 'next' ? 'Сделать следующую плату' : `Сделать плату: ${copiesOf(a.proposal.copies.length)}`, async (ev) => {
        const self = ev.currentTarget;
        self.disabled = true;
        try {
          made(a.proposal.kind === 'next' ? await post(`/pairs/${a.proposal.pair_id}/next-variations`, {})
            : await post('/photo-knowledge/plate', {device_id: view.scale.device_id, lens_id: view.scale.lens_id, material_id: view.scale.material_id, kind: a.kind,
              dot_width: a.dot_width}));
        } catch (e) { App.fail(e); self.disabled = false; }
      }, 'btn-small') : null;
      fill(el,
        h('h4', {}, `Что известно о виде «${name}» на этом лазере и титане`, status ? [' ', pill(status[0], status[1])] : null),
        b ? h('p', {class: 'small'}, h('strong', {}, a.at_best ? 'Работа на лучших измеренных настройках: ' : 'Лучшее измеренное: '),
          bestText(a.kind, b) + `${b.other_titanium ? ' (на другом титане)' : ''}${b.span_of ? ' — диапазон полоски до разворота тона' : ''}.`)
          : failed.length ? null : h('p', {class: 'small muted'}, `Этот вид на этом лазере и титане ещё не фотографировался: настройки — оценка.`),
        failed.length ? h('p', {class: 'alert warn small'}, failedText(name, failed), a.stand_in
          ? ` Вместо них — лучшие тёмные точки вида «${PhotoModes.label(a.stand_in.settings.dither)}» на этом титане: ${bestText(a.stand_in.settings.dither, a.stand_in)}`
            + `; для «${name}» это предположение, пока его не сфотографируют на этих точках.`
          : ' Тёмных точек другого вида на этом титане тоже нет: нужны точки темнее титана — по опыту процесса больше мощность, меньше скорость или шаг строк.') : null,
        a.turn && a.turn.past ? h('p', {class: 'alert warn small'}, `Max ${setting('power', a.current.power)} — дальше ${setting('power', a.turn.max_power)}, `
          + 'где тона этой шкалы разворачиваются: там больше мощности — светлее, а не темнее, и тёмные места картинки выходят светлыми.') : null,
        a.take ? h('p', {class: 'small'}, btn(a.stand_in ? `Взять тёмные точки «${PhotoModes.label(a.stand_in.settings.dither)}»`
          : a.turn && a.turn.past && !b ? 'Взять диапазон до разворота' : 'Взять лучшие настройки', () => apply(a.take), 'btn-small'),
          h('span', {class: 'muted'}, ' ' + takeText(a.take))) : null,
        Object.keys(a.effects).length ? h('ul', {class: 'small'}, Object.entries(a.effects).map(([k, e]) => effectLine(k, e))) : null,
        h('div', {class: 'row'}, Object.keys(DIRECTION).map((d) => stepButton(d, a.steps[d], apply))),
        h('p', {class: 'small muted'}, Object.keys(DIRECTION).filter((d) => !a.steps[d].refused).map((d) => `${DIRECTION[d]}: ${a.steps[d].changed.map(changeText).join(', ')}`
          + (a.steps[d].basis === 'measured' ? ' (измерено)' : ' (по опыту процесса)')).join(' · ')),
        a.proposal ? h('p', {class: 'small'}, proposal, h('span', {class: 'muted'}, (a.proposal.kind === 'next'
          ? ` Лаборатория предлагает: следующая плата вокруг копии ${a.proposal.best_label}, изменения вдвое меньше. `
          : ` Лаборатория предлагает: та же картинка вокруг ${a.status === 'unmeasured' || a.status === 'failed' ? 'лучших точек другого вида' : 'лучшего измеренного'}. `)
          + proposalText(a.proposal))) : null);
    }
    return {el, load};
  }

  /** Лучшее измеренное одной строкой: настройки, оценка и фото, по которому она. */
  const bestText = (kind, b) => `${setting('power', b.settings.power)}${kind === 'grayscale' ? ` (Min ${setting('min_power', b.settings.min_power)})` : ''}, `
    + `${setting('speed', b.settings.speed)}, ${setting('frequency', b.settings.frequency)}, ${setting('pulse_width', b.settings.pulse_width)}, `
    + `шаг ${setting('line_interval', b.settings.line_interval)}${b.settings.dot_width != null ? `, поправка точки ${setting('dot_width', b.settings.dot_width)}` : ''}`
    + ` — оценка ${value(b.score, 2)} по фото №${b.source.pair_id}`;

  /** Что лаборатория знает о каждом виде фотогравировки на лазере, линзе и титане (``GET /photo-knowledge``) и какой опыт предлагает:
      карточки для экрана «Эксперименты». ``setup`` — {device_id, lens_id, material_id}. */
  function kindCards(known, setup) {
    return known.kinds.map((k) => {
      const status = STATUS[k.status];
      const p = k.proposal;
      const make = p && (p.kind === 'next' || p.plate) ? btn(p.kind === 'next' ? 'Сделать следующую плату' : `Сделать плату: ${copiesOf(p.copies.length)}`, async (ev) => {
        const self = ev.currentTarget;
        self.disabled = true;
        try { made(p.kind === 'next' ? await post(`/pairs/${p.pair_id}/next-variations`, {}) : await post('/photo-knowledge/plate', {...setup, kind: k.kind})); }
        catch (e) { App.fail(e); self.disabled = false; }
      }, 'btn-small') : null;
      const why = !p ? (k.status === 'settled' ? 'Поиск сошёлся: это лучшие настройки вида.' : k.kind === 'grayscale'
        ? 'Начните со шкал серого (Фотогравировка → Шкалы серого).' : k.status === 'failed'
          ? 'Нужны точки темнее титана: по опыту процесса — больше мощность, меньше скорость или шаг строк.' : 'Сначала сфотографируйте любую фотогравировку точками.')
        : p.kind === 'next' ? `Следующая плата вокруг копии ${p.best_label}, изменения вдвое меньше.`
          : k.status === 'unmeasured' || k.status === 'failed' ? 'Та же картинка на лучших настройках другого вида точками.' : 'Та же картинка вокруг лучшего измеренного.';
      return h('article', {class: 'dashboard-insight pq-kind'},
        h('div', {class: 'dashboard-item-top'}, h('strong', {}, PhotoModes.label(k.kind)), status ? pill(status[0], status[1]) : null),
        h('p', {class: 'small'}, k.best ? `Лучшее: ${bestText(k.kind, k.best)}` : k.failed && k.failed.length ? failedText(PhotoModes.label(k.kind), k.failed)
          : 'Ещё не фотографировался на этом лазере и титане.'),
        Object.keys(k.effects).length ? h('ul', {class: 'small'}, Object.entries(k.effects).map(([key, e]) => effectLine(key, e))) : null,
        h('p', {class: 'small muted'}, why), p ? h('p', {class: 'small muted'}, proposalText(p)) : null, make);
    });
  }

  return {layerBox, variationsBox, advisor, kindCards, findingLine, effectText, changeText, fromPhoto, recipeFrom, SETTING};
})();
