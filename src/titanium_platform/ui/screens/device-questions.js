/* Открытые вопросы по лазеру: список считает сервер из самих данных (devices.open_questions), поэтому он меняется,
   как только вы вписали или подтвердили значение. Здесь только слова и ссылки на нужное место (DEC-039). */
'use strict';
const DeviceQuestions = (() => {
  const {h, link} = App;
  const SECTION = GlossaryController.TAB;

  /** Текст вопроса и куда перейти, чтобы на него ответить. */
  function describe(q, id) {
    const to = (tab, section) => `/devices/${id}?tab=${tab}` + (section ? `&section=${section}` : '');
    if (q.kind === 'unread') return {text: `Не прочитано на фото: ${q.key} (раздел «${SECTION[q.tab] || q.tab}»). Впишите значение.`, route: to('controller', q.tab)};
    if (q.kind === 'unconfirmed') return {text: `Значений, вписанных от руки и не подтверждённых вами: ${q.count}. Сверьте с оригиналом и нажмите ✓.`, route: to('controller', q.items[0].tab)};
    if (q.kind === 'lens') return {text: 'Не указана линза: без неё нельзя рассчитать диаметр пятна и рабочее поле. Установите линзу на вкладке «Линза».', route: to('lens')};
    if (q.kind === 'm2') return {text: 'Не задано M² (качество пучка): без него известен только диапазон пятна, и в расчётах он не участвует. Впишите M² из руководства или измерьте пятно.', route: to('lens')};

    if (q.kind === 'serial') return {text: 'Не указан серийный номер лазера.', route: to('overview')};
    return {text: q.text, route: null};
  }

  function list(d) {
    const items = d.open_questions.map((q) => describe(q, d.id));
    return h('ul', {}, items.map((x) => h('li', {}, x.text, x.route ? [' ', link(x.route, 'перейти')] : '')));
  }

  /** Раскрывающийся блок; открыт ли он по умолчанию — решает вызывающий. */
  function card(d, open = false) {
    if (!d.open_questions.length) return h('div', {class: 'alert ok'}, 'Открытых вопросов по паспорту нет.');
    return h('details', {class: 'alert warn', open}, h('summary', {}, h('strong', {}, 'Открытые вопросы по паспорту: ' + d.open_questions.length)), list(d));
  }
  return {card, list};
})();
