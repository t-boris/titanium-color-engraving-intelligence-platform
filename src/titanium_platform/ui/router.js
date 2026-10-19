/* Маршруты: адрес после «#». Неизвестный маршрут открывает «Эксперименты». Экран — объект {id, render(ctx)}. */
'use strict';
Object.assign(App, (() => {
  const {h, btn} = App;
  const screens = new Map();
  const NAV = [['/experiments', 'Эксперименты'], ['/colors', 'Карта цветов'], ['/vector', 'Векторная работа'], ['/artwork', 'Цветная гравировка'],
    ['/photo', 'Фотогравировка'], ['/photo-preview', 'Предпросмотр фотогравировки'],
    ['/designer', 'Планировщик экспериментов'], ['/findings', 'Выводы'], ['/devices', 'Лазеры'], ['/setup', 'Настройки'], ['/research', 'AI-исследователь']];
  const ROUTE_ID = {experiments: 'experiments', experiment: 'experiment', setup: 'setup', ingest: 'ingest', analysis: 'analysis', colors: 'colors', knowledge: 'colors',
    artwork: 'artwork', photo: 'photo', 'photo-preview': 'photo-preview', vector: 'vector', plans: 'plan', designer: 'designer', findings: 'findings', devices: 'devices', research: 'research'};
  const NAV_OF = {experiment: '/experiments', ingest: '/experiments', analysis: '/experiments', plans: '/experiments', knowledge: '/colors'};
  let token = 0;

  const register = (def) => screens.set(def.id, def);

  function parse() {
    const raw = (location.hash || '#/experiments').slice(1);
    const [path, qs] = raw.split('?');
    const parts = path.split('/').filter(Boolean);
    return {id: parts[0] || 'experiments', arg: parts[1], query: Object.fromEntries(new URLSearchParams(qs || '')), path: '/' + parts.join('/')};
  }

  // Иконки разделов из утверждённого прототипа v10 (DEC-019), в порядке NAV; векторная работа третья (критерий 1 фичи vector-detail-and-colour-control).
  const ICONS = [
    '<path d="M9 3v6L4 18a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-5-9V3M8 3h8M7 15h10"/>',
    '<circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18M6 6l12 12M6 18L18 6"/>',
    '<circle cx="5" cy="19" r="2"/><circle cx="19" cy="5" r="2"/><path d="M7 19c7 0 3-14 10-14M5 5h6M13 19h6"/>',
    '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="m5 17 5-5 4 3 3-6 4 6"/>',
    '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 16h2M11 13h2M15 10h2"/>',
    '<rect x="2" y="5" width="9" height="14" rx="2"/><rect x="13" y="5" width="9" height="14" rx="2"/><path d="m2 15 4-4 5 5M13 15l4-4 5 5"/>',
    '<path d="M4 19V5M4 19h16M7 15l4-5 4 2 5-7"/>',
    '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.4 1-1.8A6 6 0 0 0 12 3z"/>',
    '<path d="M3 12h4l2-6 3 12 2-8 2 4h5"/>',
    '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>',
    '<path d="M12 2v3m0 14v3M4.9 4.9 7 7m10 10 2.1 2.1M2 12h3m14 0h3M4.9 19.1 7 17M17 7l2.1-2.1"/><circle cx="12" cy="12" r="6"/><path d="m9 12 2 2 4-4"/>'];
  function icon(i) {
    const el = h('span', {class: 'nav-icon', 'aria-hidden': 'true'});
    el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + ICONS[i] + '</svg>';
    return el;
  }

  // Разделы висят слева узкой полосой со значками на каждой странице; кнопка ☰ вверху полосы (на узком экране «Меню» в шапке) открывает
  // поверх страницы окно с названиями: оно закрывается кликом вне его, Esc и переходом в раздел (DEC-081).
  const MENU_ICON = '<path d="M4 6h16M4 12h16M4 18h16"/>';
  let sidebar = null, menuButton = null, railButton = null;
  function setMenu(open) {
    if (!sidebar) return;
    if (open) sidebar.classList.add('is-open'); else sidebar.classList.remove('is-open');
    for (const b of [menuButton, railButton]) if (b) b.setAttribute('aria-expanded', String(open));
  }
  const menuOpen = () => !!sidebar && sidebar.classList.contains('is-open');
  function toggleMenu() {
    setMenu(!menuOpen());
    if (menuOpen()) sidebar.querySelector('a').focus();
  }
  function shell(active, main) {
    const toggleIcon = h('span', {class: 'nav-icon', 'aria-hidden': 'true'});
    toggleIcon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + MENU_ICON + '</svg>';
    railButton = h('button', {type: 'button', class: 'rail-toggle', title: 'Разделы', 'aria-controls': 'app-navigation', 'aria-expanded': 'false', onClick: toggleMenu},
      toggleIcon, h('span', {class: 'nav-text'}, 'Разделы'));
    sidebar = h('aside', {class: 'sidebar', id: 'app-navigation', 'aria-label': 'Разделы приложения'}, railButton,
      h('nav', {class: 'nav', 'aria-label': 'Основная навигация'},
        NAV.map(([r, l], i) => h('a', {class: 'nav-link', href: '#' + r, title: l, 'aria-current': r === active ? 'page' : null,
          onClick: () => setMenu(false)}, icon(i), h('span', {class: 'nav-text'}, l)))),
      h('p', {class: 'sidebar-note'}, 'Единственный пользователь. Все действия доступны; вход не требуется.'));
    menuButton = h('button', {type: 'button', class: 'btn btn-small mobile-menu', 'aria-controls': 'app-navigation', 'aria-expanded': 'false', onClick: toggleMenu}, 'Меню');
    return [
      h('header', {class: 'app-header'},
        h('a', {class: 'brand', href: '#/experiments'}, 'Лазерная мастерская', h('small', {}, 'Материалы · Режимы · Работы')),
        h('div', {class: 'header-actions'}, menuButton, h('span', {class: 'user-chip', title: 'Вход не требуется'}, 'Исследователь / мастер'))),
      h('div', {class: 'app-layout'}, sidebar, main)];
  }

  async function render(options = {}) {
    const preserveScroll = options.preserveScroll === true;
    const previousY = preserveScroll ? window.scrollY : 0;
    document.body.classList.remove('is-workspace');
    const previousMain = document.getElementById('main');
    const previousHeight = preserveScroll && previousMain ? previousMain.scrollHeight : 0;
    const ctx = parse();
    const mine = ++token;
    const def = screens.get(ROUTE_ID[ctx.id] || 'experiments');
    const active = NAV_OF[ctx.id] || '/' + ctx.id;
    const main = h('main', {class: 'main', id: 'main', tabindex: '-1', 'aria-busy': 'true'},
      h('div', {class: 'skeleton skeleton-title'}), h('div', {class: 'skeleton'}), h('div', {class: 'skeleton skeleton-block'}),
      h('p', {class: 'loading-label'}, 'Загружаем данные…'));
    if (preserveScroll) main.style.minHeight = Math.max(previousHeight, window.innerHeight) + 'px';
    document.getElementById('app').replaceChildren(...shell(active, main));
    if (preserveScroll) window.scrollTo(0, previousY);
    try {
      if (!def) throw new Error('Экран не найден');
      const node = await def.render(ctx);
      if (mine !== token) return;   // пользователь уже ушёл на другой экран
      const workspace = node.classList && node.classList.contains('workspace');
      const bare = workspace || (node.classList && node.classList.contains('os'));      // экран на один экран: без подвала (REQ-044)
      main.replaceChildren(...(bare ? [node] : [node, h('p', {class: 'demo'}, 'Данные хранятся на этом компьютере. RAW-результаты после проверки показываются предварительно; в стандартный прогноз входят только принятые измерения с коррекцией по эталонной карте.')]));
    } catch (e) {
      if (mine !== token) return;
      main.replaceChildren(h('div', {class: 'alert bad', role: 'alert'}, h('strong', {}, 'Не удалось загрузить данные'), h('p', {}, e.message || String(e)), btn('Повторить', render)));
    }
    main.removeAttribute('aria-busy');
    const workspace = !!main.querySelector('.workspace');       // экран на один экран: без бокового меню и прокрутки страницы (DEC-085)
    document.body.classList.toggle('is-workspace', workspace);
    if (preserveScroll) {
      window.scrollTo(0, previousY);
      requestAnimationFrame(() => { window.scrollTo(0, previousY); main.style.minHeight = ''; });
    } else window.scrollTo(0, 0);
  }

  let nextNavigationOptions = null;
  const start = () => {
    document.addEventListener('click', (ev) => {
      if (menuOpen() && !sidebar.contains(ev.target) && !(menuButton && menuButton.contains(ev.target))) setMenu(false);
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && menuOpen()) { setMenu(false); (window.innerWidth > 1000 ? railButton : menuButton).focus(); }
    });
    addEventListener('hashchange', () => { const options = nextNavigationOptions || {}; nextNavigationOptions = null; render(options); });
    render();
  };
  const go = (route, options = {}) => { nextNavigationOptions = options; location.hash = '#' + route; };
  return {screens, register, render, start, go};
})());
