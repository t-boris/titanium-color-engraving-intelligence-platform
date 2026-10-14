/* Маршруты: адрес после «#». Неизвестный маршрут открывает «Эксперименты». Экран — объект {id, render(ctx)}. */
'use strict';
Object.assign(App, (() => {
  const {h, btn} = App;
  const screens = new Map();
  const NAV = [['/experiments', 'Эксперименты'], ['/colors', 'Карта цветов'], ['/artwork', 'Цветная гравировка'],
    ['/photo', 'Фотогравировка'], ['/designer', 'Планировщик экспериментов'], ['/profiles', 'Профили']];
  const ROUTE_ID = {experiments: 'experiments', profiles: 'profiles', ingest: 'ingest', analysis: 'analysis', colors: 'colors', knowledge: 'colors',
    artwork: 'artwork', photo: 'photo', plans: 'plan', designer: 'designer'};
  const NAV_OF = {ingest: '/experiments', analysis: '/experiments', plans: '/experiments', knowledge: '/colors'};
  let token = 0;

  const register = (def) => screens.set(def.id, def);

  function parse() {
    const raw = (location.hash || '#/experiments').slice(1);
    const [path, qs] = raw.split('?');
    const parts = path.split('/').filter(Boolean);
    return {id: parts[0] || 'experiments', arg: parts[1], query: Object.fromEntries(new URLSearchParams(qs || '')), path: '/' + parts.join('/')};
  }

  async function render() {
    const ctx = parse();
    const mine = ++token;
    const def = screens.get(ROUTE_ID[ctx.id] || 'experiments');
    const active = NAV_OF[ctx.id] || '/' + ctx.id;
    const main = h('main', {class: 'main', id: 'main', tabindex: '-1', 'aria-busy': 'true'}, h('p', {class: 'muted'}, 'Загружаем данные…'));
    document.getElementById('app').replaceChildren(h('div', {class: 'shell'}, h('nav', {class: 'nav', 'aria-label': 'Разделы'}, h('h1', {}, 'Цвет титана'),
      NAV.map(([r, l]) => h('a', {href: '#' + r, 'aria-current': r === active ? 'page' : null}, l)),
      h('p', {class: 'who'}, 'Пользователь: исследователь / мастер. Все действия доступны; вход не требуется.')), main));
    try {
      if (!def) throw new Error('Экран не найден');
      const node = await def.render(ctx);
      if (mine !== token) return;   // пользователь уже ушёл на другой экран
      main.replaceChildren(node, h('p', {class: 'demo'}, 'Данные хранятся на этом компьютере. Измерения создаются только из принятых пар «файл LightBurn + фотография со стенда».'));
    } catch (e) {
      if (mine !== token) return;
      main.replaceChildren(h('div', {class: 'alert bad', role: 'alert'}, h('strong', {}, 'Не удалось загрузить данные'), h('p', {}, e.message || String(e)), btn('Повторить', render)));
    }
    main.removeAttribute('aria-busy');
  }

  const start = () => { addEventListener('hashchange', render); render(); };
  const go = (route) => { location.hash = '#' + route; };
  return {screens, register, render, start, go};
})());
