"""Research proposals require an explicit action and survive a failed creation request."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


@node
def test_proposal_is_displayed_before_creation_and_retry_does_not_create_implicitly(tmp_path):
    code = r"""
const {context, load} = require(%(dom)s);
const ctx = context({});
const info = {context_signature:'sig', name:'Line test', description:'Compare lines', summary:{size_mm:{width:20,height:30}}, test_settings:{speed:500}, time_unavailable_reason:'Time not estimated'};
const message = {id: 42, role:'assistant', content:'I suggest a test', tool_trace:[{tool:'preview_test', result:info, arguments:{}}]};
const active = {id:1, goal:'line', target:'Find a line', model:'test', insights:[], plans:[], photos:[], messages:[message], memory:null, device_id:2, lens_id:3, material_id:4};
const sessions = [{id:1, goal:'line', target:'Find a line', device_name:'Laser', lens_name:'Lens', material_name:'Titanium'}];
let attempts = 0;
const answer = (json, status=200) => ({ok:status<300,status,headers:{get:()=> 'application/json'},json:async()=>json});
ctx.fetch = async (url, opts={}) => {
  const path = String(url).split('?')[0];
  if (path === '/api/devices') return answer([{id:2,name:'Laser',lens:{name:'Lens'}}]);
  if (path === '/api/materials') return answer([{id:4}]);
  if (path === '/api/application-goals') return answer([{id:'line',name:'Lines'}]);
  if (path === '/api/research/sessions') return answer(sessions);
  if (path === '/api/research/sessions/1') return answer(active);
  if (path === '/api/research/sessions/1/proposals/42/0/create') { attempts++; return attempts === 1 ? answer({error:'No connection'}, 503) : answer({plan_id:88,plan_url:'#/plans/88'}); }
  return answer({error:path},404);
};
ctx.requestAnimationFrame = () => {};
const glue = `const screens={}; App.register=(d)=>screens[d.id]=d; globalThis.screens=screens;
App.renderMarkdown=(s)=>App.h('p',{},s); globalThis.MaterialPicker={create:()=>App.h('input',{})};`;
load(ctx,%(ui)s,[...%(tables)s,'app.js','dialogs.js',{code:glue},'screens/research.js']);
(async()=>{
 const tree=await ctx.screens.research.render({arg:'1',query:{}}); ctx.document.body.append(tree);
 const proposal=tree.querySelector('.research-proposal'), button=proposal.querySelector('button');
 const before={text:proposal.textContent, attempts};
 await button.dispatch('click'); const failure={text:proposal.textContent, disabled:button.disabled};
 await button.dispatch('click'); const done={text:proposal.textContent, hidden:button.hidden, href:proposal.querySelector('a').getAttribute('href'),attempts};
 info.pending_plan_id=77; info.pending_replaceable=true;
 const other=await ctx.screens.research.render({arg:'1',query:{}}); ctx.document.body.append(other);
 const replace=other.querySelector('.research-proposal').querySelector('button');
 await replace.dispatch('click');
 const dialog=ctx.document.body.querySelector('.modal');
 const beforeConfirm={text:dialog.textContent,attempts};
 await dialog.querySelectorAll('button').find(b=>b.textContent==='Cancel').dispatch('click');
 const afterCancel=attempts;
 await replace.dispatch('click');
 await ctx.document.body.querySelector('.modal').querySelectorAll('button').find(b=>b.textContent==='Replace and create').dispatch('click');
 console.log(JSON.stringify({before,failure,done,beforeConfirm,afterCancel,afterConfirm:attempts}));
})().catch(e=>{console.error(e.stack);process.exit(1)});
"""
    script = tmp_path / 'research.js'
    script.write_text(code % {'dom': json.dumps(str(Path(__file__).with_name('ui_dom.js'))), 'ui': json.dumps(str(UI) + '/'),
                              'tables': json.dumps(TABLES)}, encoding='utf-8')
    proc = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out['before']['attempts'] == 0 and '20 × 30 mm' in out['before']['text'] and 'Time not estimated' in out['before']['text']
    assert 'No connection' in out['failure']['text'] and not out['failure']['disabled']
    assert out['done']['hidden'] and out['done']['href'] == '#/plans/88' and out['done']['attempts'] == 2
    assert 'Plate #77' in out['beforeConfirm']['text'] and out['beforeConfirm']['attempts'] == out['afterCancel'] == 2
    assert out['afterConfirm'] == 3
