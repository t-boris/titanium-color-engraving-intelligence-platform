'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const {EventEmitter} = require('node:events');
const {compareVersions, parseLatest, fetchLatest, LATEST} = require('../src/updater');

test('versions compare numerically, a v prefix is ignored, a pre-release is below its release', () => {
  assert.equal(compareVersions('0.29.0', '0.28.9'), 1);
  assert.equal(compareVersions('v0.30.0', '0.30.0'), 0);
  assert.equal(compareVersions('0.30.0-beta.1', '0.30.0'), -1);
  assert.equal(compareVersions('0.10.0', '0.9.0'), 1);
  assert.equal(compareVersions('1.0', '1.0.0'), 0);
});

test('the latest release of GitHub is read into a version, whether it is newer, and its page', () => {
  const data = {tag_name: 'v0.30.0', prerelease: true, html_url: 'https://github.com/x/releases/tag/v0.30.0', assets: [{name: 'TitaniumWorkshop-Setup.exe'}]};
  assert.deepEqual(parseLatest(data, '0.29.0'), {version: '0.30.0', newer: true, prerelease: true, url: data.html_url, assets: ['TitaniumWorkshop-Setup.exe'], publishedAt: null});
  assert.equal(parseLatest(data, '0.30.0').newer, false);
  assert.equal(parseLatest({}, '0.29.0'), null);
  assert.equal(parseLatest(null, '0.29.0'), null);
});

function fakeGet(status, body, fail) {
  return (url, _options, callback) => {
    assert.equal(url, LATEST);
    const request = new EventEmitter();
    request.setTimeout = () => {};
    request.destroy = () => {};
    setImmediate(() => {
      if (fail) { request.emit('error', new Error('offline')); return; }
      const response = new EventEmitter();
      response.statusCode = status;
      callback(response);
      response.emit('data', body);
      response.emit('end');
    });
    return request;
  };
}

test('the check answers null when offline or refused, and the parsed release when it is there', async () => {
  assert.equal(await fetchLatest('0.29.0', {get: fakeGet(200, '', true)}), null);
  assert.equal(await fetchLatest('0.29.0', {get: fakeGet(403, '{}')}), null);
  assert.equal(await fetchLatest('0.29.0', {get: fakeGet(200, 'not json')}), null);
  const found = await fetchLatest('0.29.0', {get: fakeGet(200, JSON.stringify({tag_name: '0.31.0'}))});
  assert.equal(found.version, '0.31.0');
  assert.equal(found.newer, true);
});
