/* The desktop shell (feature electron, DEC-022, DEC-046, REQ-080): one instance; «Запуск мастерской» first; the Python core as a
   loopback child with a per-launch session secret; the window opened once at the core's session address; the core restarted once if
   it dies and an error shown after the second death; on quit the core is terminated and awaited so the port and the lock are free.
   The window is isolated (contextIsolation, sandbox, no node integration), navigates only within the core's origin, sends links to
   the system browser and gets a Content-Security-Policy. Update checks are off unless the user switches them on (DEC-048). */
'use strict';
const {app, BrowserWindow, dialog, ipcMain, session, shell, Menu} = require('electron');
const {spawn} = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');
const {Sidecar, coreCommand} = require('./sidecar');
const guards = require('./guards');
const picker = require('./workshop-picker');
const updater = require('./updater');

const REPO_ROOT = path.resolve(__dirname, '..', '..');
const SMOKE = process.argv.includes('--smoke');
let sidecar = null;
let mainWindow = null;
let pickerWindow = null;
let settings = null;

if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { const w = mainWindow || pickerWindow; if (w) { if (w.isMinimized()) w.restore(); w.focus(); } });
  app.whenReady().then(start).catch((e) => { console.error(e); app.exit(1); });
}

function userData() { return app.getPath('userData'); }

async function start() {
  settings = picker.readSettings(userData());
  Menu.setApplicationMenu(Menu.buildFromTemplate([{role: 'appMenu'}, {role: 'editMenu'}, {role: 'viewMenu'}, {role: 'windowMenu'}].filter((m) => process.platform === 'darwin' || m.role !== 'appMenu')));
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => callback(guards.permissionAllowed(permission)));
  if (SMOKE) return smoke();
  openPicker();
}

function openPicker() {
  pickerWindow = new BrowserWindow({width: 760, height: 560, title: 'Запуск мастерской', show: false,
    webPreferences: {contextIsolation: true, sandbox: true, nodeIntegration: false, preload: path.join(__dirname, 'preload.js')}});
  pickerWindow.once('ready-to-show', () => pickerWindow.show());
  pickerWindow.on('closed', () => { pickerWindow = null; if (!mainWindow && !sidecar) app.quit(); });
  pickerWindow.loadFile(path.join(__dirname, 'picker.html'));
}

ipcMain.handle('picker:choices', () => picker.choices({settings}));
ipcMain.handle('picker:browse', async (_event, mode) => {
  const result = await dialog.showOpenDialog(pickerWindow, {properties: ['openDirectory', 'createDirectory'],
    title: mode === 'new' ? 'Папка новой мастерской (пустая)' : 'Папка мастерской', buttonLabel: mode === 'new' ? 'Создать здесь' : 'Открыть'});
  if (result.canceled || !result.filePaths.length) return null;
  const folder = result.filePaths[0];
  const kind = picker.classify(folder);
  const problem = picker.problemOf(folder, kind);
  if (problem) return {error: problem};
  if (mode === 'existing' && kind === 'empty') return {error: 'В этой папке нет мастерской. Чтобы создать новую, нажмите «Создать новую мастерскую…».'};
  return {folder};
});
ipcMain.handle('picker:open', (_event, folder) => openWorkshop(folder));

/** Start the core on `folder` and open the window; the error with the core's log tail when it fails. */
async function openWorkshop(folder) {
  const where = coreCommand({resourcesPath: app.isPackaged ? process.resourcesPath : null, repoRoot: REPO_ROOT});
  sidecar = new Sidecar({spawn, command: where.command, args: where.args, env: where.env || {}, dataDir: folder, parentPid: process.pid,
    onLog: (line) => console.log('[core]', line)});
  sidecar.onDeath = onCoreDeath;
  let ready;
  try {
    ready = await sidecar.start();
  } catch (error) {
    sidecar = null;
    return {error: `Ядро мастерской не запустилось: ${error.message}`, logTail: error.logTail || ''};
  }
  settings = picker.remember(settings, folder);
  try { picker.writeSettings(userData(), settings); } catch (e) { console.warn('settings not saved', e); }
  openMain(ready);
  return {ok: true, port: ready.port};
}

function openMain(ready) {
  const origin = sidecar.url();
  session.defaultSession.webRequest.onHeadersReceived({urls: [origin + '/*']}, (details, callback) => {
    callback({responseHeaders: {...details.responseHeaders, 'Content-Security-Policy': [guards.csp(origin)]}});
  });
  mainWindow = new BrowserWindow({width: 1440, height: 920, title: 'Лазерная мастерская', show: false,
    webPreferences: {contextIsolation: true, sandbox: true, nodeIntegration: false, preload: path.join(__dirname, 'preload.js')}});
  mainWindow.webContents.on('will-navigate', (event, url) => { if (!guards.navigationAllowed(url, origin)) { event.preventDefault(); if (guards.windowOpenDecision(url) === 'external') shell.openExternal(url); } });
  mainWindow.webContents.setWindowOpenHandler(({url}) => { if (guards.windowOpenDecision(url) === 'external') shell.openExternal(url); return {action: 'deny'}; });
  mainWindow.once('ready-to-show', () => { mainWindow.show(); if (pickerWindow) { pickerWindow.close(); } });
  mainWindow.on('closed', () => { mainWindow = null; app.quit(); });
  mainWindow.loadURL(sidecar.bootstrapUrl());
  if (settings.updateChecks) checkForUpdates();
}

/** The core died on its own: once, it is started again on the same workshop; the second time the user is told. */
async function onCoreDeath(decision, {code, signal, logTail}) {
  console.error(`[shell] the core stopped (code ${code}, signal ${signal}): ${decision}`);
  if (decision === 'stopped') return;
  const folder = sidecar.dataDir;
  const deaths = sidecar.deaths;
  if (decision === 'restart') {
    const again = new Sidecar({spawn, command: sidecar.command, args: sidecar.baseArgs, env: sidecar.baseEnv, dataDir: folder, parentPid: process.pid,
      onLog: (line) => console.log('[core]', line)});
    again.deaths = deaths;
    again.onDeath = onCoreDeath;
    sidecar = again;
    try {
      await again.start();
      if (mainWindow) mainWindow.loadURL(again.bootstrapUrl());
      return;
    } catch (error) {
      logTail = error.logTail || logTail;
    }
  }
  const answer = await dialog.showMessageBox(mainWindow || undefined, {type: 'error', title: 'Ядро мастерской остановилось',
    message: 'Ядро мастерской остановилось и не смогло запуститься снова.',
    detail: `Последние строки его журнала:\n\n${logTail || '(пусто)'}`, buttons: ['Запустить снова', 'Выйти'], defaultId: 0, cancelId: 1});
  if (answer.response === 0) { sidecar.deaths = 0; sidecar.stopping = false; onCoreDeath('restart', {code, signal, logTail}); } else app.quit();
}

async function checkForUpdates() {
  const latest = await updater.fetchLatest(app.getVersion());
  if (!latest || !latest.newer || !mainWindow) return;
  const answer = await dialog.showMessageBox(mainWindow, {type: 'info', title: 'Есть новая версия',
    message: `Доступна версия ${latest.version}${latest.prerelease ? ' (предварительная)' : ''}.`,
    detail: 'Обновление устанавливается вручную: откройте страницу выпуска и загрузите установщик. Текущая работа не прерывается.',
    buttons: ['Открыть страницу выпуска', 'Позже'], defaultId: 0, cancelId: 1});
  if (answer.response === 0) shell.openExternal(latest.url);
}

/** `--smoke`: start the core on a temporary workshop, load the session address in a hidden window, ask /api/health, exit 0 or 1. */
async function smoke() {
  const folder = fs.mkdtempSync(path.join(app.getPath('temp'), 'titanium-smoke-'));
  const where = coreCommand({resourcesPath: app.isPackaged ? process.resourcesPath : null, repoRoot: REPO_ROOT});
  sidecar = new Sidecar({spawn, command: where.command, args: where.args, env: where.env || {}, dataDir: folder, parentPid: process.pid, onLog: (l) => console.log('[core]', l)});
  try {
    await sidecar.start();
    const win = new BrowserWindow({show: false, webPreferences: {contextIsolation: true, sandbox: true, nodeIntegration: false}});
    await win.loadURL(sidecar.bootstrapUrl());
    const health = await win.webContents.executeJavaScript("fetch('/api/health').then(r => r.json())");
    if (!health || health.status !== 'ok') throw new Error(`health answered ${JSON.stringify(health)}`);
    console.log(JSON.stringify({smoke: 'ok', port: sidecar.port, packaged: where.packaged}));
    await sidecar.stop();
    app.exit(0);
  } catch (error) {
    console.error('smoke failed:', error.message, error.logTail || '');
    if (sidecar) await sidecar.stop();
    app.exit(1);
  }
}

let quitting = false;
app.on('before-quit', (event) => {
  if (quitting || !sidecar) return;
  event.preventDefault();
  quitting = true;
  sidecar.stop().finally(() => { sidecar = null; app.quit(); });
});
app.on('window-all-closed', () => app.quit());
