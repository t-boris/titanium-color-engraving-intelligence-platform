'use strict';
const test = require('node:test');
const {EventEmitter} = require('node:events');
const assert = require('node:assert/strict');
const {WindowHealth, withTimeout, requestNote, watchRequests, watchWindow, PROBE_SCRIPT} = require('../src/window-health');

const blank = {children: 0, readyState: 'complete', styleSheets: 0, scripts: 85, text: 'Skip to content'};
const drawn = {children: 2, readyState: 'complete', styleSheets: 1, scripts: 85, text: 'Workshop'};

/** A health check on a fake clock: every sleep advances it, `answers` are what the page says one probe after another (the last one repeats). */
function rig(answers, options = {}) {
  const lines = [];
  const state = {time: 0, reloads: 0, probes: 0};
  const health = new WindowHealth({
    probe: async () => { const a = answers[Math.min(state.probes++, answers.length - 1)]; if (a instanceof Error) throw a; return a; },
    reload: () => { state.reloads += 1; },
    log: (scope, message) => lines.push(`[${scope}] ${message}`),
    sleep: async (ms) => { state.time += ms; },
    now: () => state.time, timeoutMs: 1000, pollMs: 250, ...options});
  return {health, lines, state};
}

test('a page that drew at once is logged as drawn and nothing is reloaded', async () => {
  const {health, lines, state} = rig([drawn]);
  assert.equal(await health.check('loaded'), 'drawn');
  assert.equal(state.reloads, 0);
  assert.match(lines.join('\n'), /interface drawn: 2 children of #app in 0 ms/);
});

test('a page that draws a little later is waited for, not reloaded', async () => {
  const {health, state} = rig([blank, blank, drawn]);
  assert.equal(await health.check('loaded'), 'drawn');
  assert.equal(state.reloads, 0);
  assert.equal(state.time, 500);
});

test('a page that never draws is described in the log and reloaded once; the reload that works restores the budget', async () => {
  const {health, lines, state} = rig([blank]);
  assert.equal(await health.check('loaded'), 'reloaded');
  assert.equal(state.reloads, 1);
  assert.match(lines.join('\n'), /interface not drawn \(loaded\): the page loaded but #app is empty \{"children":0,"readyState":"complete","styleSheets":0,"scripts":85,"text":"Skip to content"\}/);
  assert.match(lines.join('\n'), /reloading the window once, ignoring the cache/);
  const after = rig([drawn]);
  after.health.reloads = 1;
  assert.equal(await after.health.check('loaded'), 'drawn');
  assert.match(after.lines.join('\n'), /\(after 1 reload\)/);
  assert.equal(after.health.reloads, 0);
});

test('a second failure is logged as the last one and the window is not reloaded again', async () => {
  const {health, lines, state} = rig([blank]);
  assert.equal(await health.check('loaded'), 'reloaded');
  assert.equal(await health.check('loaded'), 'failed');
  assert.equal(state.reloads, 1);
  assert.match(lines.at(-1), /still not drawn after 1 reload: the window is left as it is/);
});

test('a page that cannot be asked counts as not drawn and says why', async () => {
  const {health, lines} = rig([new Error('the page did not answer in 5000 ms')]);
  assert.equal(await health.check('loaded'), 'reloaded');
  assert.match(lines.join('\n'), /the page could not be asked: the page did not answer in 5000 ms/);
});

test('a page that failed to load is not probed and goes straight to the reload', async () => {
  const {health, lines, state} = rig([drawn]);
  assert.equal(await health.check('load-failed'), 'reloaded');
  assert.equal(state.probes, 0);
  assert.match(lines.join('\n'), /interface not drawn \(load-failed\): the page did not load/);
});

test('a newer check or a reset drops the one in flight, which then neither logs nor reloads', async () => {
  const {health, lines, state} = rig([blank]);
  const first = health.check('loaded');
  health.reset();
  assert.equal(await first, 'superseded');
  const older = health.check('loaded');
  const newer = health.check('loaded');
  assert.equal(await older, 'superseded');
  assert.equal(await newer, 'reloaded');
  assert.equal(state.reloads, 1);
  assert.equal(lines.filter((l) => l.includes('reloading')).length, 1);
});

test('withTimeout passes an answer, and rejects a page that never answers', async () => {
  assert.equal(await withTimeout(Promise.resolve(7), 1000, 'late'), 7);
  await assert.rejects(withTimeout(new Promise(() => {}), 20, 'the page did not answer in 20 ms'), /did not answer in 20 ms/);
});

test('only a missing page or file and a server error of the core are worth a line; the API refusing a value is not', () => {
  const at = (path, statusCode, extra = {}) => requestNote({method: 'GET', url: `http://127.0.0.1:5000${path}`, statusCode, ...extra});
  assert.equal(at('/styles.css', 403), 'GET /styles.css answered 403');
  assert.equal(at('/screens/x.js', 404), 'GET /screens/x.js answered 404');
  assert.equal(at('/api/plans/9', 500), 'GET /api/plans/9 answered 500');
  assert.equal(at('/api/plans/9', 422), null);
  assert.equal(at('/api/plans/9', 409), null);
  assert.equal(at('/styles.css', 304), null);
  assert.equal(at('/styles.css', 200), null);
  assert.equal(at('/app.js', 0, {error: 'net::ERR_CONNECTION_REFUSED'}), 'GET /app.js failed: net::ERR_CONNECTION_REFUSED');
  assert.equal(at('/api/plans', 0, {error: 'net::ERR_ABORTED'}), null);
  assert.equal(at('/styles.css', 200, {error: 'net::OK'}), null);                    // what Electron reports for every request that went well
  assert.equal(at('/styles.css', 403, {error: 'net::OK'}), 'GET /styles.css answered 403');
  assert.equal(requestNote({method: 'GET', url: 'http://127.0.0.1:5000/styles.css?token=abc', statusCode: 403}), 'GET /styles.css answered 403');
});

test('the probe asks for the children of #app and what the page looks like', () => {
  assert.match(PROBE_SCRIPT, /getElementById\('app'\)/);
  assert.match(PROBE_SCRIPT, /children/);
  assert.match(PROBE_SCRIPT, /styleSheets/);
});

test('the window\'s events go to the log, and the check runs when the main frame loads or fails to, not for what the page replaced', () => {
  const contents = new EventEmitter();
  contents.getURL = () => 'http://127.0.0.1:5000/?token=abc';
  const lines = [];
  const checks = [];
  watchWindow(contents, {note: (scope, message) => lines.push(`[${scope}] ${message}`), check: (trigger) => checks.push(trigger)});
  contents.emit('did-finish-load');
  contents.emit('did-fail-load', {}, -3, 'ERR_ABORTED', 'http://127.0.0.1:5000/session/s3', true);
  contents.emit('did-fail-load', {}, -102, 'ERR_CONNECTION_REFUSED', 'http://127.0.0.1:5000/session/s3', true);
  contents.emit('did-fail-load', {}, -105, 'ERR_NAME_NOT_RESOLVED', 'https://example.org/a.png?x=1', false);
  contents.emit('render-process-gone', {}, {reason: 'crashed', exitCode: 11});
  contents.emit('unresponsive');
  contents.emit('responsive');
  contents.emit('console-message', {}, 1, 'just information', 3, 'http://127.0.0.1:5000/app.js');
  contents.emit('console-message', {}, 2, 'a warning', 7, 'http://127.0.0.1:5000/app.js');
  contents.emit('console-message', {}, 3, 'Refused to load the stylesheet', 1, 'http://127.0.0.1:5000/');
  assert.deepEqual(checks, ['loaded', 'load-failed']);
  assert.deepEqual(lines, [
    '[window] page loaded: /',
    '[window] page failed to load: ERR_CONNECTION_REFUSED (-102) /session/s3',
    '[window] frame failed to load: ERR_NAME_NOT_RESOLVED (-105) /a.png',
    "[window] the page's process is gone: crashed (exit code 11)",
    '[window] the page stopped responding',
    '[window] the page responds again',
    '[page] warning: a warning (/app.js:7)',
    '[page] error: Refused to load the stylesheet (/:1)']);
});

test('the requests of the core\'s origin are watched for what completed badly and for what failed', () => {
  const handlers = {};
  const webRequest = {onCompleted: (filter, fn) => { handlers.completed = {filter, fn}; }, onErrorOccurred: (filter, fn) => { handlers.failed = {filter, fn}; }};
  const lines = [];
  watchRequests(webRequest, 'http://127.0.0.1:5000', (scope, message) => lines.push(`[${scope}] ${message}`));
  assert.deepEqual(handlers.completed.filter, {urls: ['http://127.0.0.1:5000/*']});
  assert.deepEqual(handlers.failed.filter, {urls: ['http://127.0.0.1:5000/*']});
  handlers.completed.fn({method: 'GET', url: 'http://127.0.0.1:5000/styles.css', statusCode: 403, error: 'net::OK'});
  handlers.completed.fn({method: 'GET', url: 'http://127.0.0.1:5000/app.js', statusCode: 200, error: 'net::OK'});
  handlers.failed.fn({method: 'GET', url: 'http://127.0.0.1:5000/boot.js', error: 'net::ERR_CONNECTION_RESET'});
  assert.deepEqual(lines, ['[net] GET /styles.css answered 403', '[net] GET /boot.js failed: net::ERR_CONNECTION_RESET']);
});
