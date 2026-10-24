'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const picker = require('../src/workshop-picker');

/** A fake file tree keyed by POSIX paths; the code under test joins paths with the platform's separator, so lookups are normalised. */
function tree(files) {
  const posix = (p) => String(p).replace(/\\/g, '/');
  const exists = (p) => Object.prototype.hasOwnProperty.call(files, posix(p)) || Object.keys(files).some((k) => k.startsWith(posix(p) + '/'));
  const readdir = (p) => Object.keys(files).filter((k) => path.posix.dirname(k) === posix(p)).map((k) => path.posix.basename(k));
  const stat = (p) => ({isDirectory: () => files[posix(p)] === 'dir' || Object.keys(files).some((k) => k.startsWith(posix(p) + '/'))});
  return {exists, readdir, stat};
}

test('a folder is a workshop, empty, missing or something else', () => {
  const fsx = tree({'/w/titanium.sqlite': 'file', '/e': 'dir', '/o/notes.txt': 'file', '/f': 'file'});
  const kind = (p) => picker.classify(p, fsx.exists, fsx.readdir, fsx.stat);
  assert.equal(kind('/w'), 'workshop');
  assert.equal(kind('/e'), 'empty');
  assert.equal(kind('/o'), 'other');
  assert.equal(kind('/nowhere'), 'missing');
  assert.equal(kind('/f'), 'not-a-folder');
  assert.equal(picker.problemOf('/w', 'workshop'), null);
  assert.equal(picker.problemOf('/e', 'empty'), null);
  assert.match(picker.problemOf('/o', 'other'), /пустую папку/);
  assert.match(picker.problemOf('/x', 'missing'), /нет/);
});

test('the start screen offers the last workshop, the console application one and recent ones, each once, only when they exist', () => {
  const fsx = tree({'/home/.titanium-platform/titanium.sqlite': 'file', '/last/titanium.sqlite': 'file', '/gone': 'dir'});
  const settings = {lastWorkshop: '/last', recentWorkshops: ['/last', '/gone', '/home/.titanium-platform']};
  const offered = picker.choices({settings, home: '/home', exists: fsx.exists, readdir: fsx.readdir, stat: fsx.stat});
  assert.deepEqual(offered.map((c) => [c.folder, c.why]), [['/last', 'last'], ['/home/.titanium-platform', 'console']]);
  const none = picker.choices({settings: picker.DEFAULTS, home: '/elsewhere', exists: () => false, readdir: () => [], stat: () => ({isDirectory: () => true})});
  assert.deepEqual(none, []);
});

test('an opened workshop becomes the last one and the first recent one; settings survive a round trip and a broken file', () => {
  const remembered = picker.remember({...picker.DEFAULTS, recentWorkshops: ['/a', '/b']}, '/b');
  assert.equal(remembered.lastWorkshop, '/b');
  assert.deepEqual(remembered.recentWorkshops, ['/b', '/a']);
  assert.equal(remembered.updateChecks, false);
  const userData = fs.mkdtempSync(path.join(os.tmpdir(), 'shell-settings-'));
  picker.writeSettings(userData, remembered);
  assert.deepEqual(picker.readSettings(userData), remembered);
  fs.writeFileSync(picker.settingsPath(userData), '{broken');
  assert.deepEqual(picker.readSettings(userData), picker.DEFAULTS);
  assert.deepEqual(picker.readSettings(path.join(userData, 'absent')), picker.DEFAULTS);
});
