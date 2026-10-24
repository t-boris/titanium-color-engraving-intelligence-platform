/* «Запуск мастерской» (REQ-080): the workshop folder the core serves, chosen without an account. The choices: the last workshop
   opened (remembered in the shell's own settings), the console application's ~/.titanium-platform when it exists, an existing folder,
   or a new empty folder. A folder is never half-made: nothing is written until the core opens it. No Electron here. */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');

const SETTINGS_FILE = 'shell-settings.json';
const DEFAULTS = {lastWorkshop: null, recentWorkshops: [], updateChecks: false};

function settingsPath(userData) { return path.join(userData, SETTINGS_FILE); }

function readSettings(userData, read = fs.readFileSync) {
  try { return {...DEFAULTS, ...JSON.parse(read(settingsPath(userData), 'utf8'))}; } catch (e) { return {...DEFAULTS}; }
}

function writeSettings(userData, settings, write = fs.writeFileSync, mkdir = fs.mkdirSync) {
  mkdir(userData, {recursive: true});
  const tmp = settingsPath(userData) + '.tmp';
  write(tmp, JSON.stringify(settings, null, 2));
  fs.renameSync(tmp, settingsPath(userData));
}

/** Whether a folder holds a workshop (its database), is empty (a new one can be made there), or is something else. */
function classify(folder, exists = fs.existsSync, readdir = fs.readdirSync, stat = fs.statSync) {
  if (!folder || !exists(folder)) return 'missing';
  try { if (!stat(folder).isDirectory()) return 'not-a-folder'; } catch (e) { return 'unreadable'; }
  if (exists(path.join(folder, 'titanium.sqlite'))) return 'workshop';
  try { return readdir(folder).filter((n) => !n.startsWith('.')).length === 0 ? 'empty' : 'other'; } catch (e) { return 'unreadable'; }
}

/** The choices the start screen offers, in order, from the settings and the home folder. */
function choices({settings, home = os.homedir(), exists = fs.existsSync, readdir = fs.readdirSync, stat = fs.statSync}) {
  const kind = (f) => classify(f, exists, readdir, stat);
  const out = [];
  const seen = new Set();
  const add = (folder, label, why) => {
    if (!folder || seen.has(folder)) return;
    const state = kind(folder);
    if (state !== 'workshop') return;
    seen.add(folder);
    out.push({folder, label, why});
  };
  add(settings.lastWorkshop, 'Последняя мастерская', 'last');
  add(path.join(home, '.titanium-platform'), 'Мастерская консольного приложения (~/.titanium-platform)', 'console');
  for (const folder of settings.recentWorkshops || []) add(folder, 'Недавняя мастерская', 'recent');
  return out;
}

/** A folder the user picked: why it cannot be opened, or null. */
function problemOf(folder, kind) {
  if (kind === 'workshop' || kind === 'empty') return null;
  if (kind === 'missing') return 'Этой папки нет.';
  if (kind === 'not-a-folder') return 'Это не папка.';
  if (kind === 'unreadable') return 'Папку не удалось прочитать: нет прав.';
  return 'В этой папке уже есть другие файлы: выберите пустую папку или папку мастерской.';
}

/** The settings after a workshop was opened: it is the last one and first of the recent ones (at most eight). */
function remember(settings, folder) {
  const recent = [folder, ...(settings.recentWorkshops || []).filter((f) => f !== folder)].slice(0, 8);
  return {...settings, lastWorkshop: folder, recentWorkshops: recent};
}

module.exports = {readSettings, writeSettings, settingsPath, classify, choices, problemOf, remember, DEFAULTS};
