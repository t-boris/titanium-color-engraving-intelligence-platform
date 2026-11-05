'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {ShellLog, redact, MAX_LINE} = require('../src/shell-log');

const clock = () => new Date('2026-11-05T10:20:30.000Z');
const folder = () => fs.mkdtempSync(path.join(os.tmpdir(), 'shell-log-test-'));

test('a line has a UTC time, a scope and the message, and the file and its folder are created', () => {
  const file = path.join(folder(), 'logs', 'shell.log');
  const log = new ShellLog({file, now: clock});
  log.line('shell', 'start: 0.38.1');
  log.line('core', 'ready');
  assert.equal(fs.readFileSync(file, 'utf8'), '2026-11-05T10:20:30.000Z [shell] start: 0.38.1\n2026-11-05T10:20:30.000Z [core] ready\n');
});

test('the session address and the launch secret never reach the file', () => {
  const file = path.join(folder(), 'shell.log');
  const log = new ShellLog({file, now: clock});
  log.line('window', 'GET http://127.0.0.1:5000/session/AbC-123_xyz ok');
  log.addSecret('s3cr3t-value');
  log.line('page', 'cookie s3cr3t-value was sent, again s3cr3t-value');
  const text = fs.readFileSync(file, 'utf8');
  assert.ok(text.includes('/session/…'));
  assert.ok(!text.includes('AbC-123_xyz') && !text.includes('s3cr3t-value'));
  assert.equal(redact('no secret here', ['', null]), 'no secret here');
});

test('a message of several lines is indented and a very long one is cut with the size left out said', () => {
  const file = path.join(folder(), 'shell.log');
  const log = new ShellLog({file, now: clock});
  log.line('page', 'TypeError: x is not a function\n    at app.js:1\r\n    at boot.js:2');
  log.line('page', 'a'.repeat(MAX_LINE + 40));
  const lines = fs.readFileSync(file, 'utf8').split('\n');
  assert.equal(lines[0], '2026-11-05T10:20:30.000Z [page] TypeError: x is not a function');
  assert.deepEqual(lines.slice(1, 3), ['        at app.js:1', '        at boot.js:2']);
  assert.ok(lines[3].endsWith('… (40 more characters)'));
});

test('past its size the file moves to <file>.1, replacing the older one, and a new run keeps appending', () => {
  const dir = folder();
  const file = path.join(dir, 'shell.log');
  const log = new ShellLog({file, now: clock, maxBytes: 200});
  for (let i = 0; i < 12; i++) log.line('core', `line ${i} ${'x'.repeat(20)}`);
  assert.ok(fs.existsSync(`${file}.1`));
  assert.ok(fs.statSync(file).size <= 200 && fs.statSync(`${file}.1`).size <= 200);
  assert.ok(fs.readFileSync(file, 'utf8').includes('line 11'));
  const again = new ShellLog({file, now: clock, maxBytes: 200});            // the next run counts what is already there
  again.line('shell', 'next run');
  assert.ok(fs.readFileSync(file, 'utf8').trimEnd().endsWith('next run'));
});

test('a file that cannot be written is remembered and never thrown', () => {
  const blocker = path.join(folder(), 'a-file');
  fs.writeFileSync(blocker, 'x');
  const log = new ShellLog({file: path.join(blocker, 'logs', 'shell.log'), now: clock});   // its folder cannot be made
  assert.doesNotThrow(() => log.line('shell', 'still running'));
  assert.ok(log.lastError);
});
