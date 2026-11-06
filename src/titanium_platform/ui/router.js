/* Hash routes; unknown routes open Experiments. Screens provide {id, render(ctx)}. */
'use strict';
Object.assign(App, (() => {
  const {h, btn, get} = App;
  const screens = new Map();
  // Photo engraving is the fourth section; existing addresses remain available (REQ-059).
  const NAV = [['/experiments', 'Experiments'], ['/colors', 'Color map'], ['/vector', 'Vector work'], ['/photo-engraving', 'Photo engraving'],
    ['/works', 'Works'], ['/designer', 'Experiment planner'], ['/findings', 'Findings'], ['/devices', 'Lasers'], ['/setup', 'Settings'], ['/research', 'AI researcher'],
    ['/network', 'Network'], ['/labs', 'Laboratories'], ['/workshop', 'Workshop']];
  const GROUPS = [
    {label: 'Works', main: 4, children: [2, 3]},
    {label: 'Experiments', main: 0, children: [5, 6, 9]},
    {label: 'Colors and recipes', main: 1, children: []},
    {label: 'Equipment', main: 7, children: [8]},
    {label: 'Workshop', main: 12, children: [10, 11]},
  ];
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

  // Section icons follow NAV order (DEC-019, REQ-059).
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
    '<ellipse cx="9" cy="5" rx="6" ry="2.5"/><path d="M3 5v11c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V5M3 10.5C3 12 5.7 13 9 13s6-1 6-2.5M15 8h3v3"/><circle cx="19" cy="13" r="2"/><path d="M15 17h3v-2"/>'];
  function icon(i) {
    const el = h('span', {class: 'nav-icon', 'aria-hidden': 'true'});
    el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + ICONS[i] + '</svg>';
    return el;
  }

  // The navigation rail opens an overlay with section names (DEC-081).
  const MENU_ICON = '<path d="M4 6h16M4 12h16M4 18h16"/>';
  let sidebar = null, menuButton = null, railButton = null, pinButton = null;
  const pinKey = 'navigation.pinned';
  const pinned = () => { try { return localStorage.getItem(pinKey) === '1'; } catch (_) { return false; } };
  const densityKey = 'display.density';
  let density = 'normal';
  try { if (localStorage.getItem(densityKey) === 'compact') density = 'compact'; } catch (_) { /* session-only preference */ }
  function setDensity(value) {
    density = value === 'compact' ? 'compact' : 'normal';
    document.body.classList.toggle('density-compact', density === 'compact');
    try { localStorage.setItem(densityKey, density); } catch (_) { /* session-only preference */ }
  }

  // Fetch the application version once; hide the label if unavailable (REQ-057, DEC-099).
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
    const text = `The application was updated to v${version}. Reload the page to use the new version.`;
    if (updateBanner) { updateBanner.querySelector('.update-text').textContent = text; return; }
    updateBanner = h('div', {class: 'update-banner', role: 'status'}, h('span', {class: 'update-text'}, text),
      btn('Reload', () => location.reload(), 'btn-small primary'));
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
    pinButton.textContent = next ? 'Collapse menu' : 'Pin menu';
    setMenu(false);
    if (!next) railButton.focus();
  }
  function shell(active, main) {
    const toggleIcon = h('span', {class: 'nav-icon', 'aria-hidden': 'true'});
    toggleIcon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + MENU_ICON + '</svg>';
    railButton = h('button', {type: 'button', class: 'rail-toggle', title: 'Sections', 'aria-controls': 'app-navigation', 'aria-expanded': 'false', onClick: toggleMenu},
      toggleIcon, h('span', {class: 'nav-text'}, 'Sections'));
    pinButton = btn('', () => setPinned(!sidebar.classList.contains('is-pinned')), 'btn-small nav-pin');
    pinButton.setAttribute('aria-pressed', String(pinned()));
    pinButton.textContent = pinned() ? 'Collapse menu' : 'Pin menu';
    sidebar = h('aside', {class: 'sidebar' + (pinned() ? ' is-pinned' : ''), id: 'app-navigation', 'aria-label': 'Application sections'}, railButton, pinButton,
      h('nav', {class: 'nav', 'aria-label': 'Main navigation'},
        GROUPS.map(({label, main, children}) => {
          const [r] = NAV[main];
          const selected = r === active || children.some((i) => NAV[i][0] === active);
          return h('div', {class: 'nav-group' + (selected ? ' is-active' : '')},
            h('a', {class: 'nav-link', href: '#' + r, title: label, 'aria-current': r === active ? 'page' : null,
              onClick: () => setMenu(false)}, icon(main), h('span', {class: 'nav-text'}, label)),
            selected && children.length ? h('div', {class: 'nav-submenu'}, children.map((i) => {
              const [path, name] = NAV[i];
              return h('a', {class: 'nav-sublink', href: '#' + path, 'aria-current': path === active ? 'page' : null,
                onClick: () => setMenu(false)}, name);
            })) : null);
        })),
      h('p', {class: 'sidebar-note'}, 'Single-user mode. All actions are available; no sign-in is required.'));
    const menuIcon = h('span', {class: 'header-action-icon', 'aria-hidden': 'true'});
    menuIcon.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">' + MENU_ICON + '</svg>';
    menuButton = h('button', {type: 'button', class: 'btn btn-small mobile-menu header-icon-button', 'aria-label': 'Menu', title: 'Menu', 'aria-controls': 'app-navigation', 'aria-expanded': 'false', onClick: toggleMenu}, menuIcon);
    setMenu(false);
    const versionTag = h('span', {class: 'app-version', title: 'Application version'});
    showVersion(versionTag);
    return [
      h('header', {class: 'app-header'},
        h('a', {class: 'brand', href: '#/experiments'}, 'Laser workshop', ' ', versionTag, h('small', {}, 'Materials · Settings · Works')),
        h('div', {class: 'header-actions'}, menuButton, typeof Operations !== 'undefined' ? Operations.entry() : null)),
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
      h('p', {class: 'loading-label'}, 'Loading data…'));
    if (preserveScroll) main.style.minHeight = Math.max(previousHeight, window.innerHeight) + 'px';
    document.getElementById('app').replaceChildren(...shell(active, main));
    if (preserveScroll) window.scrollTo(0, previousY);
    try {
      if (!def) throw new Error('Screen not found');
      const node = await def.render(ctx);
      if (mine !== token) return;   // the user has already left the screen
      const workspace = node.classList && node.classList.contains('workspace');
      const bare = workspace || (node.classList && node.classList.contains('os'));      // single-screen layout without footer (REQ-044)
      main.replaceChildren(...(bare ? [node] : [node, h('p', {class: 'demo'}, 'Data is stored on this computer. Reviewed RAW results are provisional; standard predictions use only accepted reference-chart-corrected measurements.')]));
    } catch (e) {
      if (mine !== token) return;
      main.replaceChildren(h('div', {class: 'alert bad', role: 'alert'}, h('strong', {}, 'Could not load data'), h('p', {}, e.message || String(e)), btn('Retry', render)));
    }
    main.removeAttribute('aria-busy');
    lastHash = location.hash || '#/experiments';
    // after a move to another screen the keyboard starts at its content; a refresh of the same screen keeps whatever the person was on
    if (!preserveScroll && mine === token && main.focus) main.focus({preventScroll: true});
    const workspace = !!main.querySelector('.workspace');       // single-screen workspace without sidebar or page scrolling (DEC-085)
    document.body.classList.toggle('is-workspace', workspace);
    if (preserveScroll) {
      window.scrollTo(0, previousY);
      requestAnimationFrame(() => { window.scrollTo(0, previousY); main.style.minHeight = ''; });
    } else window.scrollTo(0, 0);
  }

  let nextNavigationOptions = null;
  const start = () => {
    setDensity(density);
    addEventListener('resize', () => setMenu(menuOpen()));
    document.addEventListener('click', (ev) => {
      if (menuOpen() && !sidebar.contains(ev.target) && !(menuButton && menuButton.contains(ev.target))) setMenu(false);
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape' && menuOpen()) { setMenu(false); (window.innerWidth > 1000 ? railButton : menuButton).focus(); }
    });
    // Skip to content (BUG-015): moves the focus to the content and leaves the address, the screen and its state alone
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
  return {screens, register, render, start, go, checkVersion, setDensity, getDensity: () => density};
})());
