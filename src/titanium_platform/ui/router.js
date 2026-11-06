/* Маршруты: адрес после «#». Неизвестный маршрут открывает «Эксперименты». Экран — объект {id, render(ctx)}. */
'use strict';
Object.assign(App, (() => {
  const {h, btn, get} = App;
  const screens = new Map();
  // REQ-059: фотогравировка — четвёртый раздел; «Цветная гравировка» (это и есть векторная работа) ушла из меню, её адрес работает;
  // непрерывная фотогравировка полосами и прогноз по файлу LightBurn открываются из раздела «Фотогравировка», их адреса прежние
  const NAV = [['/experiments', 'Эксперименты'], ['/colors', 'Карта цветов'], ['/vector', 'Векторная работа'], ['/photo-engraving', 'Фотогравировка'],
    ['/works', 'Работы'], ['/designer', 'Планировщик экспериментов'], ['/findings', 'Выводы'], ['/devices', 'Лазеры'], ['/setup', 'Настройки'], ['/research', 'AI-исследователь'],
    ['/network', 'Сеть'], ['/labs', 'Лаборатории'], ['/workshop', 'Мастерская']];
  const ROUTE_ID = {experiments: 'experiments', experiment: 'experiment', setup: 'setup', ingest: 'ingest', analysis: 'analysis', colors: 'colors', knowledge: 'colors',
    artwork: 'artwork', photo: 'photo', 'photo-preview': 'photo-preview', 'photo-engraving': 'photo-engraving', works: 'works', vector: 'vector', new: 'new', 'vector-zone': 'vector-zone', plans: 'plan', designer: 'designer',
    findings: 'findings', devices: 'devices', research: 'research', network: 'network', labs: 'labs', workshop: 'workshop'};
  const NAV_OF = {experiment: '/experiments', ingest: '/experiments', analysis: '/experiments', plans: '/experiments', knowledge: '/colors',
    artwork: '/vector', new: '/vector', 'vector-zone': '/vector', photo: '/photo-engraving', 'photo-preview': '/photo-engraving'};
  let token = 0;
  let lastHash = null;                     // the address of the screen drawn last: «#main» (the skip link) must never replace it

  const register = (def) => screens.set(def.id, def);

  function parse() {
    const raw = (location.hash || '#/experiments').slice(1);
    const [path, qs] = raw.split('?');
    const parts = path.split('/').filter(Boolean);
    return {id: parts[0] || 'experiments', arg: parts[1], query: Object.fromEntries(new URLSearchParams(qs || '')), path: '/' + parts.join('/')};
  }

  // Иконки разделов из утверждённого прототипа v10 (DEC-019), в порядке NAV; векторная работа третья (критерий 1 фичи vector-detail-and-colour-control),
  // фотогравировка четвёртая с иконкой картинки (REQ-059).
  const ICONS = [
    '<path d="M9 3v6L4 18a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-5-9V3M8 3h8M7 15h10"/>',
    '<circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18M6 6l12 12M6 18L18 6"/>',
    '<circle cx="5" cy="19" r="2"/><circle cx="19" cy="5" r="2"/><path d="M7 19c7 0 3-14 10-14M5 5h6M13 19h6"/>',
    '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="m5 17 5-5 4 3 3-6 4 6"/>',
    '<rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="3" width="8" height="8" rx="2"/><rect x="3" y="13" width="8" height="8" rx="2"/><path d="M13 14h8M13 17.5h8M13 21h5"/>',
    '<path d="M4 19V5M4 19h16M7 15l4-5 4 2 5-7"/>',
    '<path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.8V16h5v-.3c0-.7.4-1.4 1-1.8A6 6 0 0 0 12 3z"/>',
    '<path d="M3 12h4l2-6 3 12 2-8 2 4h5"/>',
    '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>',
    '<path d="M12 2v3m0 14v3M4.9 4.9 7 7m10 10 2.1 2.1M2 12h3m14 0h3M4.9 19.1 7 17M17 7l2.1-2.1"/><circle cx="12" cy="12" r="6"/><path d="m9 12 2 2 4-4"/>',
    '<path d="M2 9.5a15 15 0 0 1 20 0M5.5 13a10 10 0 0 1 13 0M9 16.5a5 5 0 0 1 6 0"/><circle cx="12" cy="20" r="1.2"/>',
    '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/><path d="M3 20h18M7 13h10"/><circle cx="18" cy="6" r="2.5"/><path d="m16.5 7.5-2 2"/>',
    '<path d="M3 11 12 4l9 7"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/><path d="M15 7.5V5h2v4"/>'];
  function icon(i) {
    const el = h('span', {class: 'nav-icon', 'aria-hidden': 'true'});
    el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + ICONS[i] + '</svg>';
    return el;
  }

  // Разделы висят слева узкой полосой со значками на каждой странице; кнопка ☰ вверху полосы (на узком экране «Меню» в шапке) открывает
  // поверх страницы окно с названиями: оно закрывается кликом вне его, Esc и переходом в раздел (DEC-081).
  const MENU_ICON = '<path d="M4 6h16M4 12h16M4 18h16"/>';
  let sidebar = null, menuButton = null, railButton = null, pinButton = null;
  const pinKey = 'navigation.pinned';
  const pinned = () => { try { return localStorage.getItem(pinKey) === '1'; } catch (_) { return false; } };

  // Версия приложения в шапке (REQ-057, DEC-099): один запрос к серверу, дальше значение берётся из памяти; если сервер не ответил, метка пуста и скрыта.
  let appVersion = null, versionAsked = false;
  function showVersion(tag) {
    if (appVersion) { tag.textContent = 'v' + appVersion; return; }
    if (versionAsked) return;
    versionAsked = true;
    get('/version').then((data) => {
      appVersion = data && data.version ? String(data.version) : null;
      for (const el of document.querySelectorAll('.app-version')) el.textContent = appVersion ? 'v' + appVersion : '';
    }).catch(() => { versionAsked = false; });
  }

  // An open page keeps its old scripts after the server is updated: the server's version is compared with the one the page loaded with
  // when the window is focused again, when the tab is visible again and every five minutes; a new version shows a «reload» banner.
  const VERSION_CHECK_MS = 5 * 60 * 1000;
  let updateBanner = null;
  function checkVersion() {
    if (!appVersion) return Promise.resolve();
    return get('/version').then((data) => {
      const now = data && data.version ? String(data.version) : null;
      if (now && now !== appVersion) showUpdate(now);
    }).catch(() => {});
  }
  function showUpdate(version) {
    const text = `Приложение обновлено до v${version} — перезагрузите страницу, чтобы работать в новой версии.`;
    if (updateBanner) { updateBanner.querySelector('.update-text').textContent = text; return; }
    updateBanner = h('div', {class: 'update-banner', role: 'status'}, h('span', {class: 'update-text'}, text),
      btn('Перезагрузить', () => location.reload(), 'btn-small primary'));
    document.body.append(updateBanner);
  }
  function watchVersion() {
    addEventListener('focus', checkVersion);
    document.addEventListener('visibilitychange', () => { if (document.visibilityState !== 'hidden') checkVersion(); });
    setInterval(checkVersion, VERSION_CHECK_MS);
  }
  function setMenu(open) {
    if (!sidebar) return;
    if (open) sidebar.classList.add('is-open'); else sidebar.classList.remove('is-open');
    const visible = open || (window.innerWidth > 1000 && sidebar.classList.contains('is-pinned'));
    for (const b of [menuButton, railButton]) if (b) b.setAttribute('aria-expanded', String(visible));
  }
  const menuOpen = () => !!sidebar && sidebar.classList.contains('is-open');
  function toggleMenu() {
    if (window.innerWidth > 1000 && sidebar.classList.contains('is-pinned')) { setPinned(false); return; }
    setMenu(!menuOpen());
    if (menuOpen()) sidebar.querySelector('a').focus();
  }
  function setPinned(next) {
    try { localStorage.setItem(pinKey, next ? '1' : '0'); } catch (_) { /* navigation still works without storage */ }
    sidebar.classList.toggle('is-pinned', next);
    pinButton.setAttribute('aria-pressed', String(next));
    pinButton.textContent = next ? 'Свернуть меню' : 'Закрепить меню';
    setMenu(false);
    if (!next) railButton.focus();
  }
  function shell(active, main) {
    const toggleIcon = h('span', {class: 'nav-icon', 'aria-hidden': 'true'});
    toggleIcon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + MENU_ICON + '</svg>';
    railButton = h('button', {type: 'button', class: 'rail-toggle', title: 'Разделы', 'aria-controls': 'app-navigation', 'aria-expanded': 'false', onClick: toggleMenu},
      toggleIcon, h('span', {class: 'nav-text'}, 'Разделы'));
    pinButton = btn('', () => setPinned(!sidebar.classList.contains('is-pinned')), 'btn-small nav-pin');
    pinButton.setAttribute('aria-pressed', String(pinned()));
    pinButton.textContent = pinned() ? 'Свернуть меню' : 'Закрепить меню';
    sidebar = h('aside', {class: 'sidebar' + (pinned() ? ' is-pinned' : ''), id: 'app-navigation', 'aria-label': 'Разделы приложения'}, railButton, pinButton,
      h('nav', {class: 'nav', 'aria-label': 'Основная навигация'},
        NAV.map(([r, l], i) => h('a', {class: 'nav-link', href: '#' + r, title: l, 'aria-current': r === active ? 'page' : null,
          onClick: () => setMenu(false)}, icon(i), h('span', {class: 'nav-text'}, l)))),
      h('p', {class: 'sidebar-note'}, 'Единственный пользователь. Все действия доступны; вход не требуется.'));
    menuButton = h('button', {type: 'button', class: 'btn btn-small mobile-menu', 'aria-controls': 'app-navigation', 'aria-expanded': 'false', onClick: toggleMenu}, 'Меню');
    setMenu(false);
    const versionTag = h('span', {class: 'app-version', title: 'Версия приложения'});
    showVersion(versionTag);
    return [
      h('header', {class: 'app-header'},
        h('a', {class: 'brand', href: '#/experiments'}, 'Лазерная мастерская', h('small', {}, 'Материалы · Режимы · Работы')),
        h('div', {class: 'header-actions'}, menuButton, versionTag, typeof Operations !== 'undefined' ? Operations.entry() : null)),        // task count and application version
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
    lastHash = location.hash || '#/experiments';
    // after a move to another screen the keyboard starts at its content; a refresh of the same screen keeps whatever the person was on
    if (!preserveScroll && mine === token && main.focus) main.focus({preventScroll: true});
    const workspace = !!main.querySelector('.workspace');       // экран на один экран: без бокового меню и прокрутки страницы (DEC-085)
    document.body.classList.toggle('is-workspace', workspace);
    if (preserveScroll) {
      window.scrollTo(0, previousY);
      requestAnimationFrame(() => { window.scrollTo(0, previousY); main.style.minHeight = ''; });
    } else window.scrollTo(0, 0);
  }

  let nextNavigationOptions = null;
  const start = () => {
    addEventListener('resize', () => setMenu(menuOpen()));
    document.addEventListener('click', (ev) => {
      if (menuOpen() && !sidebar.contains(ev.target) && !(menuButton && menuButton.contains(ev.target))) setMenu(false);
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && menuOpen()) { setMenu(false); (window.innerWidth > 1000 ? railButton : menuButton).focus(); }
    });
    // «Перейти к содержимому» (BUG-015): moves the focus to the content and leaves the address, the screen and its state alone
    const skipTo = () => {
      const main = document.getElementById('main');
      if (main && main.focus) main.focus();
    };
    document.addEventListener('click', (ev) => {
      const link = ev.target && ev.target.closest ? ev.target.closest('a.skip') : null;
      if (!link) return;
      ev.preventDefault();
      skipTo();
    });
    addEventListener('hashchange', () => {
      if (location.hash === '#main') {                       // a way to the link the click handler did not catch: undo the address
        if (history.replaceState && lastHash) history.replaceState(null, '', lastHash);
        skipTo();
        return;
      }
      const options = nextNavigationOptions || {}; nextNavigationOptions = null; render(options);
    });
    watchVersion();
    render();
  };
  const go = (route, options = {}) => { nextNavigationOptions = options; location.hash = '#' + route; };
  return {screens, register, render, start, go, checkVersion};
})());
