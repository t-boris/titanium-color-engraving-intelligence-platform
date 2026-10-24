/* Цвет точек с карты цветов (0.25.0, DEC-118). Работа фотогравировки в виде точками (Jarvis, Аткинсон…) открывает карту цветов в режиме
   выбора: #/colors?dots=<работа>&setup=<лазер и линза>; фотозона векторной работы (0.27.0) — #/colors?dots=<работа>&zone=<номер>&setup=…,
   с &from=editor — из вкладки «Фото» редактора. Сверху полоса называет работу (и зону), её вид и ширину и ведёт обратно; фильтр лазера и
   линзы — работы. Цвет на карте или в поиске справа даёт кнопку «Точки этим цветом»: тон шкалы серого ставит точки на эту шкалу при его
   мощности, заливка — на её настройки (шаг строк становится шагом точек). Цвет, который точками быть не может, говорит почему и на карте
   бледнее. После выбора экран возвращается туда, откуда открыт: к работе, к экрану зоны или к редактору. */
'use strict';
const DotPick = (() => {
  const {h, btn, post, go, toast, fail} = App;
  const value = (v, d = 1) => (v == null ? '—' : String(+(+v).toFixed(d)).replace('.', ','));
  const kindName = (key) => { const t = PhotoModes.label(key); return t.charAt(0).toUpperCase() + t.slice(1); };
  const setupKey = (scale) => `laser:${scale.device_id}/lens:${scale.lens_id == null ? 'unknown' : scale.lens_id}`;

  /** Адрес карты цветов, на которой выбирают цвет точек работы ``view`` (её лазер и линза — фильтр карты). */
  const address = (view) => `/colors?dots=${view.id}&setup=${encodeURIComponent(setupKey(view.scale))}`;
  /** Адрес карты цветов для точек фотозоны ``number`` векторной работы ``work`` ({id, device_id, lens_id}); ``from`` 'editor' — вернуться
      в редактор работы, иначе — на экран зоны. */
  const zoneAddress = (work, number, from = null) => `/colors?dots=${work.id}&zone=${number}&setup=${encodeURIComponent(setupKey(work))}`
    + (from ? `&from=${from}` : '');
  /** Чей цвет точек выбирается (``pick.work``; ``from`` — откуда открыта карта): что назвать в полосе, куда вернуться и куда сохранить. */
  function owner(pick) {
    const w = pick.work;
    if (w.zone == null) return {name: `работы «${w.name}»`, back: `/photo-engraving?work=${w.id}`, backText: '← К работе без изменений',
      save: `/photo-works/${w.id}/settings`, done: 'Цвет точек выбран: работа покажет точки этим цветом'};
    const editor = pick.from === 'editor';
    return {name: `фотозоны ${w.zone} работы «${w.name}»`, back: editor ? `/vector?plan=${w.id}` : `/vector-zone?work=${w.id}&zone=${w.zone}`,
      backText: editor ? '← К работе без изменений' : '← К зоне без изменений', save: `/vector/${w.id}/photo/${w.zone}/settings`,
      done: 'Цвет точек выбран: зона покажет точки этим цветом'};
  }
  /** Чем цвет карты ``point`` станет для точек (``scale`` и ``power`` либо ``fill``) или почему не может (``reason``); ``pick`` — что
      карта получила вместе с цветами (/api/colors?dots=<работа>): сама работа и каждый цвет её лазера и линзы. */
  const of = (pick, point) => pick.groups[point.group] || {reason: null};
  const can = (pick, point) => !of(pick, point).reason && !!pick.groups[point.group];

  /** Полоса над картой: для какой работы выбирается цвет точек, что подходит и как вернуться без выбора. */
  function banner(pick) {
    const w = pick.work, who = owner(pick);
    const grade = w.material && w.material.grade ? `титане ${w.material.grade}` : 'титане работы';
    return h('div', {class: 'alert dp-banner', role: 'note'},
      h('div', {class: 'stack'},
        h('strong', {}, `Цвет точек для ${who.name} · ${kindName(w.kind)} · ${value(w.width_mm)} мм`),
        h('span', {class: 'small'}, 'Нажмите цвет на карте или найдите нужный справа и выберите «Точки этим цветом». '
          + `Подходят цвета этого лазера и линзы на ${grade}: тона шкал серого и заливки с шагом строк от ${value(pick.step_min_mm, 4)} мм; остальные на карте бледнее.`)),
      h('a', {class: 'btn btn-small', href: `#${who.back}`}, who.backText));
  }

  /** Что точки получат от цвета ``point``: настройки тона шкалы или заливки. */
  function what(found, point) {
    const p = point.parameters || {};
    const settings = `${value(p.speed)} мм/с · ${value(p.frequency)} кГц · ${p.pulse_width == null ? 'импульс не указан' : value(p.pulse_width, 0) + ' нс'} · шаг ${value(p.line_interval, 4)} мм`;
    return found.scale ? `Точки встанут на эту шкалу серого при ${value(found.power)} %: ${settings}.`
      : `Точки будут бить на настройках этой заливки: ${value(p.power)} % · ${settings}; шаг строк станет шагом точек.`;
  }

  /** Под цветом карты или найденным рецептом: кнопка «Точки этим цветом» или почему этот цвет точками быть не может. */
  function action(pick, point) {
    const found = of(pick, point);
    if (!pick.groups[point.group]) return h('p', {class: 'small muted dp-action'}, 'Для точек этот цвет не подходит: другой лазер или линза, чем у работы.');
    if (found.reason) return h('p', {class: 'small muted dp-action'}, `Для точек этот цвет не подходит: ${I18N.tr(pick.reasons[found.reason] || found.reason)}.`);
    const go_ = btn('Точки этим цветом', async (ev) => {
      const self = ev.currentTarget;
      self.disabled = true;
      self.textContent = 'Сохраняем…';
      const who = owner(pick);
      try {
        await post(who.save, {dot_colour: point.group});
        toast(who.done, 'ok');
        go(who.back);
      } catch (e) { fail(e); self.disabled = false; self.textContent = 'Точки этим цветом'; }
    }, 'primary btn-small');
    return h('div', {class: 'row dp-action'}, go_, h('span', {class: 'small muted'}, what(found, point)));
  }

  return {address, zoneAddress, can, banner, action};
})();
