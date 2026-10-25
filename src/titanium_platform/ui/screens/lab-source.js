/* Источник измерений работы (feature electron, REQ-085): собственные измерения мастерской или выпуск подключённой лаборатории с его лазером,
   линзой и титаном. Выбор — при создании работы («Источник измерений» в форме векторной работы из фотографии и в «Новой работе»
   фотогравировки); собственные измерения выбраны по умолчанию, лаборатория никогда не подставляется сама. Открытая работа, закреплённая за
   выпуском, показывает полосу источника: лаборатория, дата и хеш выпуска, публичное название лазера, линза, титан, условия и причину, по
   которой работа не пересчитывается (замороженный результат). «Обновить источник» и «Вернуться к прежнему источнику» — явные шаги с
   предпросмотром: пока шаг не подтверждён, работа не меняется. Весь текст из выпуска попадает на экран только текстовыми узлами h(). */
'use strict';
const LabSource = (() => {
  const {h, fill, btn, pill, get, post, modal, toast, fail, num, labText, swatch, table} = App;
  const short = (sha) => String(sha || '').slice(0, 12);
  const day = (iso) => String(iso || '').slice(0, 10);
  const when = (iso) => String(iso || '').replace('T', ' ').slice(0, 16);
  const laserName = (l) => (l ? l.public_name || [l.manufacturer, l.model].filter(Boolean).join(' ') || 'лазер' : 'лазер не указан');
  const lensName = (l) => (l ? (l.focal_length_mm == null ? 'линза' : `линза ${+l.focal_length_mm} мм`) : 'линза неизвестна');
  const materialName = (m) => (m ? [m.family, m.grade, m.thickness_mm == null ? null : `${+m.thickness_mm} мм`].filter(Boolean).join(' · ') || 'титан' : 'титан не указан');
  const setupName = (s) => [laserName(s.laser), lensName(s.lens), s.material ? materialName(s.material) : null].filter(Boolean).join(' · ');
  const releaseName = (r) => `выпуск от ${day(r.release_created_at || r.created_at)} · ${short(r.content_sha256)}`;
  const BASIS = {chart: 'по эталонной карте', clean: 'относительно чистого титана', 'as-shot': 'как снято, без привязки'};
  const hexChip = (hex) => (hex ? h('span', {class: 'sw', style: `background:${hex}`, title: hex}) : h('span', {class: 'sw ge-none', title: 'цвет не измерен'}));
  const chipOf = (c) => (c ? h('span', {}, swatch(c.lab), labText(c.lab)) : h('span', {class: 'muted'}, 'не измерен'));

  /** «Источник измерений» новой работы: собственные измерения (по умолчанию) или лазер, линза и титан, измеренные выпуском подключённой
      лаборатории (GET /labs/choices). ``kind`` 'vector' — только установки с титаном, 'photo' — любые. ``value()`` — поле формы ``source``:
      null или {release_id, laser, lens, material?} с идентификаторами выпуска. */
  function picker(kind, {onChange = null} = {}) {
    const select = h('select', {'aria-label': 'Источник измерений'}, h('option', {value: ''}, 'Мои измерения'));
    const hint = h('span', {class: 'small muted'}, 'по умолчанию — измерения этой мастерской');
    const options = [];                                    // option value n → {lab, setup}
    const chosen = () => (select.value === '' ? null : options[+select.value - 1] || null);
    const value = () => {
      const c = chosen();
      if (!c) return null;
      const out = {release_id: c.lab.release.release_id, laser: c.setup.laser.uuid, lens: c.setup.lens ? c.setup.lens.uuid : null};
      if (kind === 'vector') out.material = c.setup.material.uuid;
      return out;
    };
    const loaded = get('/labs/choices').then((labs) => {
      for (const lab of labs) {
        for (const setup of lab.setups) {
          if (kind === 'vector' && !setup.material) continue;
          options.push({lab, setup});
          select.append(h('option', {value: String(options.length)}, `${lab.name}: ${setupName(setup)} (фото ${setup.photographs})`));
        }
      }
      if (!options.length) hint.textContent = 'подключённых лабораторий с измерениями нет: используются измерения этой мастерской';
    }).catch(() => { hint.textContent = 'подключённые лаборатории недоступны: используются измерения этой мастерской'; });
    select.addEventListener('change', () => {
      const c = chosen();
      fill(hint, c ? [`${c.lab.name}, ${releaseName(c.lab.release)}`, c.lab.release.verified ? null : ' · подпись не проверена',
        '. Цвета и кривые — измерения другой лаборатории на её лазере: тот же цвет на этом лазере не обещан.'] : 'по умолчанию — измерения этой мастерской');
      if (onChange) onChange(value());
    });
    const el = h('label', {class: 'f'}, h('span', {}, 'Источник измерений'), select, hint);
    return {el, select, hint, value, chosen, loaded};
  }

  // ---- the source of an open work ------------------------------------------------------------------------------------------------

  /** The conditions of a work's source, each translated; the frozen reason is shown apart and left out here. */
  const conditionList = (s) => (s.conditions || []).filter((c) => c !== s.frozen).map((c) => h('li', {}, I18N.tr(c)));

  /** Полоса источника открытой работы, закреплённой за выпуском (``work.source.kind === 'release'``); при собственных измерениях скрыта.
      ``base`` — адрес работы ('/vector/12' или '/photo-works/12'), ``kind`` 'vector' | 'photo', ``applied(work)`` получает работу, как её
      вернул сервер после подтверждённого шага. ``update(work)`` перерисовывает полосу из работы. */
  function banner(base, kind, applied) {
    const el = h('div', {class: 'lab-banner alert', role: 'note', 'aria-label': 'Источник измерений работы', hidden: true});
    function update(work) {
      const s = work && work.source;
      el.hidden = !s || s.kind !== 'release';
      if (el.hidden) return fill(el);
      const conditions = conditionList(s);
      return fill(el,
        h('div', {class: 'row lab-banner-head'}, h('strong', {}, 'Источник: лаборатория '), h('span', {class: 'lab-name'}, s.lab_name), pill(releaseName(s)),
          s.withdrawn_hidden ? pill(`отозванных измерений исключено: ${s.withdrawn_hidden}`, 'warn') : null),
        h('p', {class: 'small lab-setup'}, `${laserName(s.laser)} · ${lensName(s.lens)} · ${materialName(s.material)}`
          + (s.pinned_at ? ` · закреплено ${when(s.pinned_at)}` : '') + (s.versions ? ` · прежних источников: ${s.versions}` : '')),
        conditions.length ? h('ul', {class: 'small lab-conditions'}, conditions) : null,
        s.frozen ? h('p', {class: 'alert bad lab-frozen', role: 'alert'}, h('strong', {}, 'Результат заморожен. '), I18N.tr(s.frozen)) : null,
        work.confirmed ? h('p', {class: 'small'}, 'Подтверждённый файл: ', h('a', {href: work.confirmed.file}, work.confirmed.name || 'файл LightBurn'),
          ` · подтверждён ${when(work.confirmed.at)}`) : null,
        h('div', {class: 'row'}, btn('Обновить источник', () => step({}), 'btn-small'),
          s.versions > 0 ? btn('Вернуться к прежнему источнику', () => step({back: true}), 'btn-small') : null));
    }
    async function step(request) {
      let preview;
      try { preview = await post(`${base}/source`, request); } catch (e) { return fail(e); }
      return previewDialog(preview, kind, request, async () => {
        const made = await post(`${base}/source`, {...request, confirm: true});
        toast(request.back ? 'Работа вернулась к прежнему источнику' : 'Источник работы обновлён', 'ok');
        applied(made.work);
      });
    }
    return {el, update};
  }

  /** Предпросмотр шага: куда перейдёт работа и что изменится; «Подтвердить» делает шаг. */
  function previewDialog(p, kind, request, confirm) {
    const to = p.to || {};
    const where = h('p', {}, request.back ? 'Работа вернётся к источнику: ' : 'Работа перейдёт на источник: ', h('strong', {}, to.lab_name),
      `, ${releaseName(to)}; ${laserName(to.laser)} · ${lensName(to.lens)}` + (to.material ? ` · ${materialName(to.material)}` : '')
      + (to.withdrawn_hidden ? `; отозванных измерений исключено: ${to.withdrawn_hidden}` : ''));
    return modal(request.back ? 'Вернуться к прежнему источнику' : 'Обновить источник работы', h('div', {class: 'stack lab-preview'}, where,
      to.frozen ? h('p', {class: 'alert bad'}, I18N.tr(to.frozen)) : null,
      kind === 'vector' ? vectorPreview(p) : photoPreview(p),
      h('p', {class: 'small muted'}, 'Пока шаг не подтверждён, работа не меняется. Прежний источник сохраняется: к нему можно вернуться.')), [
      {label: 'Отмена', run: (m) => m.close()},
      {label: 'Подтвердить', cls: 'primary', run: async (m) => { await confirm(); m.close(); }}]);
  }

  /** What the step does to the colours of a vector work: a colour a line (was → will be, ΔE), the colours that go missing and the largest
      changes first, by pages (a work may hold dozens of colours, DEC-090). */
  function vectorPreview(p) {
    const entries = p.entries || [];
    const change = (e) => (e.missing ? 'missing' : e.delta_e > 0 ? 'changed' : 'same');
    const colours = entries.length ? App.list({items: entries,
      row: (e) => [chipOf(e.before), h('span', {class: 'muted'}, '→'), chipOf(e.after),
        e.missing ? pill('в новом источнике не измерен', 'bad') : e.delta_e == null ? h('span', {class: 'muted'}, 'ΔE —')
          : e.delta_e > 0 ? h('span', {}, `ΔE ${num(e.delta_e, 1)}`) : pill('без изменений', 'ok')],
      filters: [{key: 'change', label: 'Что станет с цветом', options: [['missing', 'пропадут'], ['changed', 'изменятся'], ['same', 'без изменений']],
        test: (e, v) => change(e) === v}],
      sorts: [['largest', 'Сначала большие изменения', (a, b) => (b.missing ? 1 : 0) - (a.missing ? 1 : 0) || (b.delta_e ?? -1) - (a.delta_e ?? -1)],
        ['work', 'Как в работе']]}).el : h('p', {class: 'muted'}, 'Работа пока не использует цвета источника');
    const zones = p.zones || [];
    return h('div', {class: 'stack'},
      h('p', {class: 'small'}, `Цветов в работе: ${entries.length}; изменятся: ${p.changed || 0}; пропадут: ${p.missing || 0}`
        + (p.max_delta_e != null ? `; наибольшая разница ΔE ${num(p.max_delta_e, 1)}` : '') + '.'),
      colours,
      zones.length ? h('div', {}, h('p', {class: 'small'}, 'Фотозоны:'),
        h('ul', {class: 'small'}, zones.map((z) => h('li', {}, `зона ${z.zone}: `, z.problem ? I18N.tr(z.problem) : 'шкала измерена в новом источнике')))) : null);
  }

  function photoPreview(p) {
    if (p.problem) return h('p', {class: 'alert warn'}, I18N.tr(p.problem));
    const rows = (p.steps || []).map((s) => [num(s.power, 1), hexChip(s.before), hexChip(s.after), s.delta_e == null ? '—' : num(s.delta_e, 1)]);
    return h('div', {class: 'stack'},
      h('p', {class: 'small'}, p.max_delta_e != null ? `Наибольшая разница цвета шкалы от Min до Max: ΔE ${num(p.max_delta_e, 1)}.` : 'Цвет шкалы сравнить не удалось.'),
      table(['Мощность, %', 'Было', 'Станет', 'ΔE'], rows, 'Шкала не сравнивалась', true));
  }

  return {picker, banner, previewDialog, short, day, when, laserName, lensName, materialName, setupName, releaseName, BASIS, hexChip};
})();
