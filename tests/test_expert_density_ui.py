"""Display density is persistent and can be changed without navigating away."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_vector_work import TABLES, UI


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_display_density_persists_and_degrades_to_a_session_preference(tmp_path):
    script = tmp_path / 'density.js'
    code = r'''
const {context, load} = require(%(dom)s);
const stored = new Map([['display.density', 'compact']]);
function make(fail) {
  const ctx = context({});
  ctx.localStorage = {getItem: k => { if (fail) throw Error('denied'); return stored.get(k); },
    setItem: (k, v) => { if (fail) throw Error('denied'); stored.set(k, v); }};
  load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'router.js', 'screens/setup.js']);
  return ctx;
}
(async () => {
  const ctx = make(false);
  const selected = ctx.App.getDensity();
  const view = await ctx.App.screens.get('setup').render({query: {tab: 'display'}});
  const select = view.querySelector('select');
  const initial = select.value;
  select.value = 'normal'; await select.dispatch('change');
  const normal = [ctx.App.getDensity(), ctx.document.body.classList.contains('density-compact'), stored.get('display.density')];
  select.value = 'compact'; await select.dispatch('change');
  const compact = [ctx.App.getDensity(), ctx.document.body.classList.contains('density-compact'), stored.get('display.density')];
  const denied = make(true); denied.App.setDensity('compact');
  console.log(JSON.stringify({selected, initial, normal, compact, restored: make(false).App.getDensity(), denied: denied.App.getDensity()}));
})().catch(e => { console.error(e.stack); process.exit(1); });
'''
    script.write_text(code % {'dom': json.dumps(str(Path(__file__).with_name('ui_dom.js'))),
                              'ui': json.dumps(str(UI) + '/'), 'tables': json.dumps(TABLES)})
    proc = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {'selected': 'compact', 'initial': 'compact', 'normal': ['normal', False, 'normal'],
                                      'compact': ['compact', True, 'compact'], 'restored': 'compact', 'denied': 'compact'}


@pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')
def test_light_study_is_explicit_and_does_not_change_the_default_theme(tmp_path):
    script = tmp_path / 'study.js'
    code = r'''
const {context, load} = require(%(dom)s);
async function run(search) {
  const ctx = context({});
  ctx.location.search = search;
  ctx.addEventListener = () => {};
  ctx.setInterval = () => 0;
  ctx.document.querySelectorAll = s => ctx.document.body.querySelectorAll(s);
  ctx.localStorage = {getItem: () => null, setItem: () => {}};
  const app = ctx.document.createElement('div'); app.setAttribute('id', 'app'); ctx.document.body.append(app);
  load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'router.js']);
  ctx.App.register({id: 'experiments', render: async () => ctx.App.h('div', {}, 'Study task')});
  ctx.App.start();
  await new Promise(resolve => setTimeout(resolve, 0));
  const note = ctx.document.body.querySelector('.theme-study-note');
  return {light: ctx.document.body.classList.contains('theme-study-light'), note: note && note.textContent};
}
(async () => console.log(JSON.stringify([await run(''), await run('?theme-study=light')])))()
  .catch(e => { console.error(e.stack); process.exit(1); });
'''
    script.write_text(code % {'dom': json.dumps(str(Path(__file__).with_name('ui_dom.js'))),
                              'ui': json.dumps(str(UI) + '/'), 'tables': json.dumps(TABLES)})
    proc = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == [{'light': False, 'note': None},
                                       {'light': True, 'note': 'Light theme study preview · not a released theme'}]
