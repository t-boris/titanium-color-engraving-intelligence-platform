'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {csp, navigationAllowed, windowOpenDecision, permissionAllowed} = require('../src/guards');

test('the window navigates only within the core origin', () => {
  const origin = 'http://127.0.0.1:43210';
  assert.ok(navigationAllowed('http://127.0.0.1:43210/session/abc', origin));
  assert.ok(navigationAllowed('http://127.0.0.1:43210/#/vector', origin));
  assert.equal(navigationAllowed('http://127.0.0.1:8765/', origin), false);
  assert.equal(navigationAllowed('https://example.org/', origin), false);
  assert.equal(navigationAllowed('file:///etc/passwd', origin), false);
  assert.equal(navigationAllowed('not a url', origin), false);
});

test('links go to the system browser only when they are http(s)', () => {
  assert.equal(windowOpenDecision('https://github.com/t-boris'), 'external');
  assert.equal(windowOpenDecision('http://example.org/'), 'external');
  assert.equal(windowOpenDecision('file:///Users/x'), 'deny');
  assert.equal(windowOpenDecision('javascript:alert(1)'), 'deny');
  assert.equal(windowOpenDecision('smb://nas/share'), 'deny');
  assert.equal(windowOpenDecision('nonsense'), 'deny');
});

test('the content security policy names the core origin and forbids objects, framing and foreign bases', () => {
  const policy = csp('http://127.0.0.1:1');
  assert.match(policy, /default-src 'self' http:\/\/127\.0\.0\.1:1/);
  assert.match(policy, /object-src 'none'/);
  assert.match(policy, /frame-ancestors 'none'/);
  assert.match(policy, /base-uri 'none'/);
  assert.match(policy, /img-src [^;]*blob:/);
  assert.doesNotMatch(policy, /unsafe-eval/);
});

test('pages get no camera, microphone or location', () => {
  for (const p of ['media', 'geolocation', 'notifications', 'midi', 'openExternal']) assert.equal(permissionAllowed(p), false);
  assert.equal(permissionAllowed('clipboard-read'), true);
});
