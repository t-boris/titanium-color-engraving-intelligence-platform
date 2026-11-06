'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const {context} = require('../../tests/ui_dom');
const source = fs.readFileSync(path.join(__dirname, '../src/picker.js'), 'utf8');

async function screen(choices) {
  const ctx = context({});
  ctx.document.querySelectorAll = (selector) => ctx.document.body.querySelectorAll(selector);
  for (const [tag, id] of [['div', 'known'], ['div', 'status'], ['details', 'log-details'], ['pre', 'log'], ['button', 'open-existing'], ['button', 'create-new']]) {
    const node = ctx.document.createElement(tag); node.setAttribute('id', id); ctx.document.body.append(node);
  }
  const calls = [];
  ctx.window.shell = {picker: {choices: async () => choices, browse: async () => null,
    open: async (folder, mode) => { calls.push([folder, mode]); return {error: 'Failed to start', logTail: 'detailed log'}; }}};
  vm.runInContext(source, ctx);
  await new Promise((resolve) => setTimeout(resolve, 0));
  return {ctx, calls};
}

test('continue last workshop, keep alternatives and show startup details separately', async () => {
  const {ctx, calls} = await screen([{why: 'last', label: 'Last workshop', folder: '/last'}, {why: 'recent', label: 'Recent workshop', folder: '/other'}]);
  const known = ctx.document.getElementById('known');
  const button = known.querySelectorAll('button').find((b) => b.textContent === 'Continue');
  assert.ok(button);
  assert.match(known.querySelector('details').textContent, /Other known workshops/);
  await button.dispatch('click');
  assert.deepEqual(calls, [['/last', 'existing']]);
  assert.match(ctx.document.getElementById('status').textContent, /Failed to start/);
  assert.equal(ctx.document.getElementById('log-details').hidden, false);
  assert.match(ctx.document.getElementById('log').textContent, /detailed log/);
  assert.equal(button.disabled, false);
});

test('unavailable last workshop explains the problem and leaves other folders accessible', async () => {
  const {ctx} = await screen([{why: 'last', label: 'Last workshop', folder: '/gone', problem: 'This folder does not exist.'}]);
  const known = ctx.document.getElementById('known');
  assert.match(known.textContent, /This folder does not exist/);
  assert.equal(known.querySelectorAll('button').length, 0);
  assert.equal(ctx.document.getElementById('open-existing').disabled, false);
});
