"""Device navigation keeps old routes while grouping technical data."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


@node
def test_all_device_routes_remain_reachable_and_technical_section_opens_for_deep_links(tmp_path):
    script = tmp_path / 'device.js'
    code = r"""
const {context, load} = require(%(dom)s);
const device = {id: 5, title: 'Laser', manufacturer: 'JPT', model: 'M7', lens: null, open_questions: [], documents: [], passport: {waveforms: [], pulse_steps: []}};
const ctx = context({'/api/devices/5': {status: 200, json: device}, '/api/devices/5/charts': {status: 200, json: {curves: []}},
  '/api/devices/5/capability-results': {status: 200, json: []}, '/api/experiments': {status: 200, json: []}, '/api/lenses': {status: 200, json: []}});
const create = ctx.document.createElement; ctx.document.createElement = (tag) => { const node = create(tag); node.dataset = {}; return node; };
const glue = `
const screens = {}; App.register = (d) => screens[d.id] = d; globalThis.screens = screens;
const card = () => App.h('div', {}, 'content');
globalThis.DeviceView = {experimentsCard: card, documentsCard: card, capabilityResultsCard: card, passportCard: card, stepsCard: card};
globalThis.DeviceCalc = {calculator: card};
globalThis.DevicePlots = {cutoff: card, energy: card, byFrequency: card};
globalThis.DeviceReport = {waveformsCard: card, reportCard: card};
globalThis.DeviceLens = {card: async () => card()};
globalThis.DeviceController = {controllerCard: card};
globalThis.DeviceCharacterCard = {card};
globalThis.DeviceForms = {editForm: card};`;
load(ctx, %(ui)s, [...%(tables)s, 'app.js', 'dialogs.js', {code: glue}, 'screens/device.js']);
(async () => {
 const result = {};
 for (const tab of ['overview', 'experiments', 'lens', 'controller', 'charts', 'pulses', 'report', 'documents']) {
   const tree = await ctx.screens.devices.render({arg:'5', query:{tab}});
   const nav = tree.querySelector('.device-navigation'), details = nav.querySelector('details');
   result[tab] = {open: details.hasAttribute('open'), primary: nav.children[0].querySelectorAll('a').map(a => a.getAttribute('href')),
     technical: details.querySelectorAll('a').map(a => a.getAttribute('href')),
     active: nav.querySelectorAll('a').filter(a => a.getAttribute('aria-current') === 'page').map(a => a.getAttribute('href'))};
 }
 console.log(JSON.stringify(result));
})().catch(e => { console.error(e.stack); process.exit(1); });
"""
    script.write_text(code % {'dom': json.dumps(str(Path(__file__).with_name('ui_dom.js'))), 'ui': json.dumps(str(UI) + '/'),
                              'tables': json.dumps(TABLES)}, encoding='utf-8')
    proc = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    primary = ['#/devices/5?tab=' + t for t in ('overview', 'experiments', 'lens', 'controller')]
    technical = ['#/devices/5?tab=' + t for t in ('charts', 'pulses', 'report', 'documents')]
    for tab, state in result.items():
        assert state['primary'] == primary and state['technical'] == technical
        assert state['active'] == ['#/devices/5?tab=' + tab]
        assert state['open'] == (tab in {'charts', 'pulses', 'report', 'documents'})
