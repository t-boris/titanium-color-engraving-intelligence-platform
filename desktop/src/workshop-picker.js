/* workshop startup (REQ-080): the workshop folder the core serves, chosen without an account. The choices: the last workshop
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


/** Recover an unambiguous shell settings file after a product-name change. Never overwrite it here. */
function previousSettings(userData) {
  const parent = path.dirname(userData);
  const found = [];
  try {
    for (const entry of fs.readdirSync(parent, {withFileTypes: true})) {
      if (!entry.isDirectory() || path.join(parent, entry.name) === userData) continue;
      const file = settingsPath(path.join(parent, entry.name));
      try {
        if (fs.statSync(file).size > 65536) continue;
        const value = JSON.parse(fs.readFileSync(file, 'utf8'));
        if (typeof value.lastWorkshop === 'string' && Array.isArray(value.recentWorkshops)
            && value.recentWorkshops.every((folder) => typeof folder === 'string')
            && typeof value.updateChecks === 'boolean') found.push({...DEFAULTS, ...value});
      } catch (_) { /* Not a readable shell settings file. */ }
    }
  } catch (_) { return null; }
  return found.length === 1 ? found[0] : null;
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
    if (state !== 'workshop') {
      if (why === 'last') { seen.add(folder); out.push({folder, label, why, problem: problemOf(folder, state) || 'The folder no longer contains a workshop.'}); }
      return;
    }
    seen.add(folder);
    out.push({folder, label, why});
  };
  add(settings.lastWorkshop, 'Last workshop', 'last');
  add(path.join(home, '.titanium-platform'), 'Command-line workshop (~/.titanium-platform)', 'console');
  for (const folder of settings.recentWorkshops || []) add(folder, 'Recent workshop', 'recent');
  return out;
}

/** A folder the user picked: why it cannot be opened, or null. */
function problemOf(folder, kind) {
  if (kind === 'workshop' || kind === 'empty') return null;
  if (kind === 'missing') return 'This folder does not exist.';
  if (kind === 'not-a-folder') return 'This is not a folder.';
  if (kind === 'unreadable') return 'Cannot read the folder: permission denied.';
  return 'This folder contains other files. Choose an empty folder or a workshop folder.';
}

/** The settings after a workshop was opened: it is the last one and first of the recent ones (at most eight). */
function remember(settings, folder) {
  const recent = [folder, ...(settings.recentWorkshops || []).filter((f) => f !== folder)].slice(0, 8);
  return {...settings, lastWorkshop: folder, recentWorkshops: recent};
}

module.exports = {readSettings, previousSettings, writeSettings, settingsPath, classify, choices, problemOf, remember, DEFAULTS};
