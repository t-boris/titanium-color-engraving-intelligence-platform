/* Эксперименты и наблюдения: платы, планы и входные пары (REQ-003, REQ-015). Диалог платы — plate-dialog.js. */
'use strict';
(() => {
  const {h, btn, link, pill, get, del, toast, confirmBox, table} = App;

  const PAIR_KIND = {'Awaiting check': ['Ожидает проверки', ''], 'Needs correction': ['Требует исправления', 'warn'],
    'Ready to accept': ['Готова к принятию', 'ok'], Accepted: ['Принята', 'ok']};
  const MODE = {'Calibration plate': 'Калибровочная плата', 'Discrete color engraving': 'Цветная гравировка', 'Tonal photo engraving': 'Тональная фотогравировка',
    'Color-path photo engraving': 'Фотогравировка по цветовому пути', 'Restored from file': 'Восстановленный из файла'};
  const PLAN_STATUS = {Draft: 'Черновик', 'Ready to export': 'Готов к экспорту', Exported: 'Экспортирован'};

  App.register({id: 'experiments', async render() {
    const [profiles, plans, pairs, setups] = await Promise.all([get('/profiles'), get('/plans'), get('/pairs'), get('/setups')]);
    const reload = () => App.render();
    const noProfile = !profiles.length;
    const head = h('div', {class: 'row'}, h('div', {}, h('h2', {}, 'Эксперименты и наблюдения'),
      h('p', {class: 'sub'}, 'Определения плат, планы гравировки и пары «файл LightBurn + фотография».')),
    h('span', {class: 'spacer'}), btn('Создать плату', () => PlateDialog.open(profiles, reload), 'primary', noProfile),
    link('/ingest', 'Добавить наблюдение'), link('/designer', 'Спланировать следующий эксперимент'));
    if (noProfile) return h('div', {class: 'stack'}, head, h('div', {class: 'card empty'}, h('h3', {}, 'Сначала настройте профиль лазера'), link('/profiles', 'Профили')));
    if (!plans.length && !pairs.length) {
      return h('div', {class: 'stack'}, head, h('div', {class: 'card empty'}, h('h3', {}, 'Пока нет экспериментов'), h('p', {}, 'Создайте калибровочную плату или добавьте пару файлов.')));
    }
    const planRows = plans.map((p) => [link('/plans/' + p.id, p.name), MODE[p.mode] || p.mode, pill(PLAN_STATUS[p.status] || p.status), p.layers,
      btn('Удалить план', () => confirmBox('Удалить план', `«${p.name}». Действие необратимо. План, связанный с сохранёнными парами, удалить нельзя.`, 'Удалить',
        async () => { await del('/plans/' + p.id); toast('Запись удалена', 'ok'); reload(); }), 'danger')]);
    const pairRows = pairs.map((p) => {
      const [label, kind] = PAIR_KIND[p.status] || [p.status, ''];
      const remove = p.status === 'Accepted' ? '' : btn('Удалить пару', () => confirmBox('Удалить пару', 'Действие необратимо. Принятую пару и её измерения удалить нельзя.', 'Удалить',
        async () => { await del('/pairs/' + p.id); toast('Запись удалена', 'ok'); reload(); }), 'danger');
      return [link(p.status === 'Accepted' ? '/analysis/' + p.id : '/ingest?pair=' + p.id, p.lightburn_name), p.photo_name, pill(label, kind), p.created_at.slice(0, 10), remove];
    });
    return h('div', {class: 'stack'}, head,
      !setups.length ? h('div', {class: 'alert warn'}, 'Стенд не настроен: без него пару принять нельзя. ', link('/profiles?tab=stand', 'Настроить стенд')) : null,
      h('div', {class: 'card'}, h('h3', {}, 'Планы гравировки и платы'), table(['Название', 'Режим', 'Состояние', 'Слоёв', ''], planRows, 'Планов пока нет')),
      h('div', {class: 'card'}, h('h3', {}, 'Входные пары'), table(['Файл LightBurn', 'Фотография', 'Состояние', 'Добавлена', ''], pairRows, 'Пар пока нет')));
  }});
})();
