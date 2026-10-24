'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const path = require('node:path');
const {Sidecar, parseReadyLine, coreCommand, coreArgs, restartDecision} = require('../src/sidecar');

function fakeChild() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  child.killed = [];
  child.kill = (signal) => { child.killed.push(signal); setImmediate(() => child.emit('exit', null, signal)); };
  return child;
}

test('the ready line is the JSON line of the core and nothing else', () => {
  assert.deepEqual(parseReadyLine('{"ready": true, "port": 51234, "pid": 7, "version": "0.29.0"}'), {port: 51234, pid: 7, version: '0.29.0'});
  assert.equal(parseReadyLine('titanium-platform 0.29.0: http://127.0.0.1:8765'), null);
  assert.equal(parseReadyLine('{"ready": false, "port": 1}'), null);
  assert.equal(parseReadyLine('{"ready": true, "port": "abc"}'), null);
  assert.equal(parseReadyLine('{not json'), null);
});

test('the core command is the packaged binary when it is there, else the development venv', () => {
  const packaged = coreCommand({resourcesPath: '/App/Resources', repoRoot: '/repo', platform: 'darwin', exists: (p) => p.endsWith('titanium-core')});
  assert.deepEqual(packaged, {command: path.join('/App/Resources', 'titanium-core', 'titanium-core'), args: [], packaged: true});
  const dev = coreCommand({resourcesPath: null, repoRoot: '/repo', platform: 'darwin', exists: () => false, env: {}});
  const own = coreCommand({resourcesPath: null, repoRoot: '/repo', platform: 'darwin', exists: () => false, env: {TCE_CORE_PYTHON: '/py'}});
  assert.equal(own.command, '/py');
  assert.equal(dev.command, path.join('/repo', '.venv', 'bin', 'python'));
  assert.deepEqual(dev.args, ['-m', 'titanium_platform']);
  assert.equal(dev.env.PYTHONPATH, path.join('/repo', 'src'));
  const win = coreCommand({resourcesPath: 'C:\\App\\resources', repoRoot: 'C:\\repo', platform: 'win32', exists: () => false, env: {}});
  assert.ok(win.command.endsWith(path.join('.venv', 'Scripts', 'python.exe')));
  assert.deepEqual(coreArgs('/w', 42), ['--desktop', '--port', '0', '--parent-pid', '42', '--data-dir', '/w']);
});

test('the core is restarted once, never in a loop, and not when the shell stops it', () => {
  assert.equal(restartDecision(1), 'restart');
  assert.equal(restartDecision(2), 'give-up');
  assert.equal(restartDecision(5), 'give-up');
  assert.equal(restartDecision(1, {stopping: true}), 'stopped');
});

test('start resolves with the port and the session address once the core says ready, with the secret in its environment', async () => {
  let spawned;
  const child = fakeChild();
  const sidecar = new Sidecar({spawn: (command, args, options) => { spawned = {command, args, options}; return child; }, command: 'core',
    dataDir: '/w', parentPid: 99, timeoutMs: 1000});
  const started = sidecar.start();
  assert.equal(spawned.command, 'core');
  assert.deepEqual(spawned.args, ['--desktop', '--port', '0', '--parent-pid', '99', '--data-dir', '/w']);
  assert.equal(spawned.options.env.TCE_SESSION_SECRET, sidecar.secret);
  assert.equal(spawned.options.env.TCE_DESKTOP, '1');
  assert.ok(sidecar.secret.length >= 24);
  child.stderr.emit('data', 'warning: something\n');
  child.stdout.emit('data', '{"ready": true, "po');
  child.stdout.emit('data', 'rt": 43210, "pid": 5}\n');
  const ready = await started;
  assert.equal(ready.port, 43210);
  assert.equal(ready.url, 'http://127.0.0.1:43210');
  assert.equal(sidecar.bootstrapUrl(), `http://127.0.0.1:43210/session/${sidecar.secret}`);
  assert.ok(sidecar.log.includes('warning: something'));
});

test('a core that dies before ready, or never says ready, rejects with the log tail', async () => {
  const dead = fakeChild();
  const one = new Sidecar({spawn: () => dead, command: 'core', dataDir: '/w', parentPid: 1, timeoutMs: 1000});
  const p = one.start();
  dead.stderr.emit('data', 'Traceback: boom\n');
  dead.emit('exit', 1, null);
  await assert.rejects(p, (e) => e.message.includes('before it was ready') && e.logTail.includes('Traceback: boom'));
  const silent = fakeChild();
  const two = new Sidecar({spawn: () => silent, command: 'core', dataDir: '/w', parentPid: 1, timeoutMs: 20});
  await assert.rejects(two.start(), /did not report ready in time/);
});

test('a death after ready calls onDeath with the restart decision; stop terminates and waits', async () => {
  const child = fakeChild();
  const sidecar = new Sidecar({spawn: () => child, command: 'core', dataDir: '/w', parentPid: 1, timeoutMs: 1000});
  const deaths = [];
  sidecar.onDeath = (decision, info) => deaths.push([decision, info.code]);
  const started = sidecar.start();
  child.stdout.emit('data', '{"ready": true, "port": 1234, "pid": 5}\n');
  await started;
  child.emit('exit', 3, null);
  assert.deepEqual(deaths, [['restart', 3]]);
  assert.equal(sidecar.deaths, 1);
  const again = fakeChild();
  const second = new Sidecar({spawn: () => again, command: 'core', dataDir: '/w', parentPid: 1, timeoutMs: 1000});
  const p2 = second.start();
  again.stdout.emit('data', '{"ready": true, "port": 1235, "pid": 6}\n');
  await p2;
  await second.stop();
  assert.deepEqual(again.killed, ['SIGTERM']);
  assert.equal(second.child, null);
  await second.stop();                       // nothing to stop twice
});
