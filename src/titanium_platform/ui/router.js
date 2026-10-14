/* Маршруты: адрес после «#». Неизвестный маршрут открывает «Эксперименты». Экран — объект {id, render(ctx)}. */
'use strict';
Object.assign(App, (() => {
  const {h, btn} = App;
  const screens = new Map();
  const NAV = [['/experiments', 'Эксперименты'], ['/colors', 'Карта цветов'], ['/artwork', 'Цветная гравировка'],
    ['/photo', 'Фотогравировка'], ['/designer', 'Планировщик экспериментов'], ['/devices', 'Лазеры'], ['/profiles', 'Профили']];
  const ROUTE_ID = {experiments: 'experiments', profiles: 'profiles', ingest: 'ingest', analysis: 'analysis', colors: 'colors', knowledge: 'colors',
    artwork: 'artwork', photo: 'photo', plans: 'plan', designer: 'designer', devices: 'devices'};
  const NAV_OF = {ingest: '/experiments', analysis: '/experiments', plans: '/experiments', knowledge: '/colors'};
  let token = 0;

  const register = (def) => screens.set(def.id, def);

  function parse() {
    const raw = (location.hash || '#/experiments').slice(1);
    const [path, qs] = raw.split('?');
    const parts = path.split('/').filter(Boolean);
    return {id: parts[0] || 'experiments', arg: parts[1], query: Object.fromEntries(new URLSearchParams(qs || '')), path: '/' + parts.join('/')};
  }

  // Иконки разделов из утверждённого прототипа v10 (DEC-019), в порядке NAV.
  const ICONS = [
    '<path d="M9 3v6L4 18a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-5-9V3M8 3h8M7 15h10"/>',
    '<circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18M6 6l12 12M6 18L18 6"/>',
    '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="m5 17 5-5 4 3 3-6 4 6"/>',
    '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 16h2M11 13h2M15 10h2"/>',
    '<path d="M4 19V5M4 19h16M7 15l4-5 4 2 5-7"/>',
    '<path d="M3 12h4l2-6 3 12 2-8 2 4h5"/>',
    '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>'];
  function icon(i) {
    const el = h('span', {class: 'nav-icon', 'aria-hidden': 'true'});
    el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + ICONS[i] + '</svg>';
    return el;
  }

  let sidebar = null, menuButton = null;
  function shell(active, main) {
    sidebar = h('aside', {class: 'sidebar', id: 'app-navigation', 'aria-label': 'Разделы приложения'},
      h('nav', {class: 'nav', 'aria-label': 'Основная навигация'},
        NAV.map(([r, l], i) => h('a', {class: 'nav-link', href: '#' + r, 'aria-current': r === active ? 'page' : null,
          onClick: () => { sidebar.classList.remove('is-open'); }}, icon(i), l))),
      h('p', {class: 'sidebar-note'}, 'Единственный пользователь. Все действия доступны; вход не требуется.'));
    menuButton = h('button', {type: 'button', class: 'btn btn-small mobile-menu', 'aria-controls': 'app-navigation', 'aria-expanded': 'false', onClick: () => {
      const open = sidebar.classList.toggle('is-open');
      menuButton.setAttribute('aria-expanded', String(open));
      if (open) sidebar.querySelector('a').focus();
    }}, 'Меню');
    return [
      h('header', {class: 'app-header'},
        h('a', {class: 'brand', href: '#/experiments'}, 'Цвет титана', h('small', {}, 'Измерения · Знания · Гравировка')),
        h('div', {class: 'header-actions'}, menuButton, h('span', {class: 'user-chip', title: 'Вход не требуется'}, 'Исследователь / мастер'))),
      h('div', {class: 'app-layout'}, sidebar, main)];
  }

  async function render() {
    const ctx = parse();
    const mine = ++token;
    const def = screens.get(ROUTE_ID[ctx.id] || 'experiments');
    const active = NAV_OF[ctx.id] || '/' + ctx.id;
    const main = h('main', {class: 'main', id: 'main', tabindex: '-1', 'aria-busy': 'true'},
      h('div', {class: 'skeleton skeleton-title'}), h('div', {class: 'skeleton'}), h('div', {class: 'skeleton skeleton-block'}),
      h('p', {class: 'loading-label'}, 'Загружаем данные…'));
    document.getElementById('app').replaceChildren(...shell(active, main));
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
