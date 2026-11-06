"""Shared target selection distinguishes a screen sample from a measured recipe."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from test_vector_work import TABLES, UI

node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


@node
def test_target_color_supports_precise_values_picker_and_keyboard_coordinates(tmp_path):
    code = r"""
const {context,load} = require(%(dom)s); const ctx=context({});
const make=ctx.document.createElement; let pixel=[255,0,0,255], drawn=null;
ctx.document.createElement=(tag)=>{ const el=make(tag);
  if(tag==='canvas') el.getContext=()=>({clearRect(){},drawImage(...args){drawn=args.slice(1,3)},getImageData(){return {data:pixel}}});
  return el;
};
load(ctx,%(ui)s,[...%(tables)s,'app.js']);
(async()=>{
 const picked=[]; const target=ctx.App.targetColor({initial:[50,0,0],imageUrl:'/image.png',onSelect:v=>picked.push(Array.from(v))});
 ctx.document.body.append(target.el);
 const details=target.el.querySelector('details'), img=details.querySelector('img');
 details.open=true; await details.dispatch('toggle');
 img.naturalWidth=100; img.naturalHeight=80; await img.dispatch('load');
 const nums=details.querySelectorAll('input').filter(e=>e.getAttribute('type')==='number');
 nums[0].value='17'; nums[1].value='23'; await details.querySelectorAll('button')[0].dispatch('click');
 const sampled={drawn,picked:picked.slice(),note:details.textContent};
 pixel=[1,2,3,0]; await details.querySelectorAll('button')[0].dispatch('click');
 const transparent={count:picked.length,note:details.textContent};
 target.inputs[0].value='48.123'; target.inputs[1].value='-17.456'; target.inputs[2].value='7.89'; await target.apply.dispatch('click');
 const exact=picked[picked.length-1];
 target.picker.value='#00ff00'; await target.picker.dispatch('input');
 console.log(JSON.stringify({url:img.src,sampled,transparent,exact,green:picked[picked.length-1],label:target.el.textContent}));
})().catch(e=>{console.error(e.stack);process.exit(1)});
"""
    script = tmp_path / 'target.js'
    script.write_text(code % {'dom': json.dumps(str(Path(__file__).with_name('ui_dom.js'))), 'ui': json.dumps(str(UI) + '/'),
                              'tables': json.dumps(TABLES)}, encoding='utf-8')
    proc = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result['url'] == '/image.png' and result['sampled']['drawn'] == [17, 23]
    assert result['sampled']['picked'] == [[53.2, 80.1, 67.2]] and 'not a measured titanium color' in result['sampled']['note']
    assert result['transparent']['count'] == 1 and 'transparent' in result['transparent']['note']
    assert result['exact'] == [48.123, -17.456, 7.89] and result['green'] == [87.7, -86.2, 83.2]
    assert 'not a measured titanium color' in result['label']
