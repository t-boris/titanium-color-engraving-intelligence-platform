(function () {
  'use strict';
  const h = App.h, KEY = 'titanium.continuous.v1';
  const E = {profile:'Профиль лазера',model:'Модель цветового пространства',function:'Передаточная функция',knowledge:'Запись знания',observation:'Наблюдение',plan:'План гравировки'};
  const all = entity => DB.list(entity,{pageSize:100000,sort:'createdAt',dir:'asc'}).items;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (_) {}
  let state = {mode:'Тональный',profileId:'laser-1',image:{name:'Анна-портрет.png',demo:true},bandCount:'32',transferId:'',markers:true,path:[],allowed:[],planId:null,...saved};
  let host, busy = false, failure = null, empty = false, generation = 0;
  const get = (entity,id) => id ? DB.get(entity,id) : null;
  const button = (label,fn,kind='',disabled=false) => h('button',{type:'button',class:'btn '+kind,disabled:disabled || busy,onClick:fn},label);
  const link = (label,route) => h('a',{href:'#'+route},label);
  const number = value => value == null ? 'Не определено' : Number(value).toLocaleString('ru-RU',{maximumFractionDigits:3});
  const labText = lab => lab ? `Lab ${number(lab.L)} · ${number(lab.a)} · ${number(lab.b)}` : 'Прогноз пока недоступен';
  function persist() {
    try { localStorage.setItem(KEY,JSON.stringify(state)); }
    catch (_) { App.toast('Не удалось сохранить черновик в браузере. Он доступен до закрытия страницы.','warning'); }
  }
  function rgb(lab) {
    if (!lab) return '#d9dce3';
    let y=(lab.L+16)/116,x=y+lab.a/500,z=y-lab.b/200;
    const f=v=>v**3>0.008856?v**3:(v-16/116)/7.787;
    x=f(x)*0.95047;y=f(y);z=f(z)*1.08883;
    const gamma=v=>Math.round(Math.max(0,Math.min(1,v<=0.0031308?12.92*v:1.055*v**(1/2.4)-0.055))*255);
    return `rgb(${gamma(x*3.2406-y*1.5372-z*0.4986)},${gamma(-x*0.9689+y*1.8758+z*0.0415)},${gamma(x*0.0557-y*0.204+z*1.057)})`;
  }
  const swatch = lab => h('span',{class:'swatch',style:{background:rgb(lab)},'aria-label':labText(lab)});
  const observations = () => all(E.observation).filter(o=>o.profileId===state.profileId && o.modelEligibility?.allowed);
  const knowledge = () => all(E.knowledge).filter(k=>k.profileId===state.profileId);
  const complete = k => k?.lab && Number.isFinite(k.confidence) && Number.isFinite(k.expectedDeltaE) && k.stability?.assessed;
  function usable(k,allowed=state.allowed) {
    return complete(k) && ['Валидировано','Производственное'].includes(k.stage) && (!k.questionable || (state.mode==='Тональный' && k.stage==='Производственное') || (state.mode==='Цветовой путь' && allowed.includes(k.id)));
  }
  const functions = () => all(E.function).filter(t=>t.profileId===state.profileId && t.mode===state.mode);
  const draft = () => get(E.plan,state.planId);
  function invalidate() { state.planId=null;failure=null;generation++;persist(); }
  function field(label,input,help) {
    const id='continuous-field-'+(++field.counter);input.id=id;
    return h('div',{class:'field'},h('label',{for:id},label),input,help?h('span',{class:'field-help'},help):null);
  }
  field.counter=0;
  function currentFunction() { return get(E.function,state.transferId); }
  function validFunction(t) {
    return t && t.profileId===state.profileId && t.mode===state.mode && t.points?.length && t.points.every(p=>usable(get(E.knowledge,p.knowledgeId)));
  }
  async function action(label,fn) {
    if (busy) return;
    busy=true;failure=null;draw(label);
    try { await fn();persist(); }
    catch (error) { failure={message:error.message || 'Не удалось рассчитать фотогравировку',retry:()=>action(label,fn)}; }
    finally { busy=false;draw(); }
  }
  function ensureDraft() {
    let p=draft();
    if (p && p.profileId===state.profileId && p.mode===(state.mode==='Тональный'?'Тональная фотогравировка':'Фотогравировка по цветовому пути')) return p;
    p=DB.createPhotoDraft({mode:state.mode,profileId:state.profileId,image:state.image,bandCount:Number(state.bandCount),transferId:state.transferId,markers:state.markers,name:(state.image?.name || 'Фотогравировка')+' — '+state.mode.toLowerCase()});
    state.planId=p.id;
    if (state.mode==='Цветовой путь' && state.allowed.length) p=DB.allowQuestionable(p.id,state.allowed);
    persist();return p;
  }
  function functionInfo(t) {
    if (!t) return h('p',{class:'alert'},'Для выбранного режима нет калиброванной передаточной функции');
    const points=t.points || [];
    const chart=h('div',{class:'continuous-curve'});
    const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');
    svg.setAttribute('viewBox','0 0 360 145');svg.setAttribute('role','img');svg.setAttribute('aria-label',state.mode==='Тональный'?'Кривая ожидаемой яркости по входной яркости':'Цветовая траектория по входной яркости');
    const axis=document.createElementNS(ns,'path');axis.setAttribute('d','M30 12V115H345');axis.setAttribute('fill','none');axis.setAttribute('stroke','#b8c0cd');svg.append(axis);
    const poly=document.createElementNS(ns,'polyline');poly.setAttribute('points',points.map(p=>`${30+p.brightness*310},${115-p.lab.L}`).join(' '));poly.setAttribute('fill','none');poly.setAttribute('stroke','#0066d6');poly.setAttribute('stroke-width','3');svg.append(poly);
    points.forEach(p=>{const c=document.createElementNS(ns,'circle');c.setAttribute('cx',30+p.brightness*310);c.setAttribute('cy',115-p.lab.L);c.setAttribute('r','5');c.setAttribute('fill',rgb(p.lab));c.setAttribute('stroke','#fff');svg.append(c);});
    chart.append(svg,h('p',{class:'muted text-sm'},'Входная яркость: 0 → 1 · вертикальная ось: L, 0 → 100'));
    const body=h('div',{class:'stack'},chart,h('p',{class:'text-sm'},'Наблюдения-основания: '+(t.observationIds || []).length+' · Модель: '+(get(E.model,t.modelId)?.version || 'Неизвестно')),
      h('p',{class:'muted text-sm'},t.assessment?.description || 'Демонстрационная передаточная функция'),button('Наблюдения-основания',()=>evidence(t.observationIds || [])));
    if (state.mode==='Тональный') body.append(h('p',{},'Ожидаемая яркость: '+(t.assessment?.brightness || []).map(number).join(' → ')+' · Контраст: '+number(t.assessment?.contrast)));
    else body.append(h('div',{class:'row'},...(t.path || []).map((id,i)=>{const k=get(E.knowledge,id);return h('div',{class:'continuous-path-chip'},swatch(k?.lab),h('small',{},(i+1)+'. '+labText(k?.lab)));})),h('p',{class:'muted text-sm'},'Оценка результата: ΔE вдоль выбранной траектории.'));
    if (!validFunction(t)) body.append(h('p',{class:'alert alert-warning'},'Функция содержит параметры, недоступные для этого режима или плана. Выберите другую функцию или калибруйте по совместимым измерениям.'));
    return body;
  }
  function evidence(ids,title='Наблюдения-основания') {
    const rows=ids.map(id=>get(E.observation,id)).filter(Boolean);
    App.modal({title,body:h('div',{class:'stack'},h('p',{class:'muted'},'Сохранённые измерения доступны только для чтения.'),...rows.map(o=>{
      const k=knowledge().find(k=>k.observationIds?.includes(o.id));
      return h('div',{class:'alert'},h('div',{class:'row'},swatch(o.lab),h('strong',{},o.id),link('Открыть анализ','/analysis/'+encodeURIComponent(o.pairId))),h('p',{},labText(o.lab)),h('p',{class:'text-sm'},`Мощность ${number(o.parameters.power)} % · Частота ${number(o.parameters.frequency)} кГц · Скорость ${number(o.parameters.speed)} мм/с`),h('p',{class:'text-sm'},'Партия или лист: '+(o.batch || 'Неизвестно')+' · Фокус: '+number(o.focus)+' · '+o.alignmentMethod),h('p',{class:'text-sm'},'Допуск к модели: '+o.modelEligibility.reason),h('p',{class:'text-sm'},'Допуск к независимым повторам: '+o.repeatEligibility.reason),k?link('Запись знания','/knowledge/'+encodeURIComponent(k.id)):null);
    }),!rows.length?h('p',{},'Нет совместимых наблюдений'):null),actions:[{label:'Закрыть',onClick:api=>api.close()}]});
  }
  function calibrate() {
    const obs=observations(), selected=new Set(obs.map(o=>o.id));
    const error=h('p',{class:'field-error',role:'alert',hidden:true});
    const body=h('div',{class:'stack'},h('p',{},state.mode==='Тональный'?'По выбранным измерениям строится монотонная кривая яркость → параметры.':'Функция строится по выбранной цветовой траектории и её измерениям.'),state.mode==='Цветовой путь'?h('p',{},'Цветов в траектории: '+state.path.length):null,
      obs.length?h('div',{class:'continuous-observation-list'},...obs.map(o=>h('label',{class:'check'},h('input',{type:'checkbox',checked:true,onChange:e=>e.target.checked?selected.add(o.id):selected.delete(o.id)}),h('span',{},o.id+' · '+labText(o.lab)+' · '+(o.batch || 'Неизвестно'))))):h('p',{class:'alert'},'Нет совместимых наблюдений'),error);
    App.modal({title:'Калибровать по измерениям',body,actions:[{label:'Отмена',onClick:api=>api.close()},{label:'Построить функцию',kind:'primary',onClick:async api=>{
      error.hidden=true;
      try {
        const t=await DB.run('calibrateTransfer',{profileId:state.profileId,mode:state.mode,observationIds:[...selected],path:state.path,allowedQuestionableIds:state.allowed});
        state.transferId=t.id;invalidate();api.close();draw();App.toast('Передаточная функция построена','success');
      } catch(e) { error.textContent=e.message;error.hidden=false; }
    }}]});
  }
  function selectPath() {
    let path=state.path.slice();
    const choices=knowledge().filter(k=>usable(k)),list=h('div',{class:'stack'}),error=h('p',{class:'field-error',role:'alert',hidden:true});
    function update() {
      list.replaceChildren(h('p',{class:'muted'},'Выберите цвета в порядке прохождения от тёмных областей фотографии к светлым.'),h('div',{class:'continuous-palette'},...choices.map(k=>button(labText(k.lab)+(path.includes(k.id)?' · Выбран':''),()=>{if(!path.includes(k.id))path.push(k.id);update();},path.includes(k.id)?'btn-primary':''))),h('div',{class:'stack'},...path.map((id,i)=>{
        const k=get(E.knowledge,id);
        return h('div',{class:'row'},swatch(k?.lab),h('span',{},(i+1)+'. '+labText(k?.lab)),button('Выше',()=>{[path[i-1],path[i]]=[path[i],path[i-1]];update();},'btn-small',i===0),button('Ниже',()=>{[path[i],path[i+1]]=[path[i+1],path[i]];update();},'btn-small',i===path.length-1),button('Убрать',()=>{path.splice(i,1);update();},'btn-small'));
      })),!choices.length?h('p',{class:'alert'},'Нет допустимых цветов для этой версии профиля'):null);
    }
    update();
    App.modal({title:'Выбрать траекторию',body:h('div',{},list,error),actions:[{label:'Отмена',onClick:api=>api.close()},{label:'Применить путь',kind:'primary',onClick:async api=>{
      error.hidden=true;
      if(!path.length || !path.every(id=>usable(get(E.knowledge,id)))) {error.textContent='Выберите допустимую непустую траекторию';error.hidden=false;return;}
      try {
        const t=await DB.run('calibrateTransfer',{profileId:state.profileId,mode:'Цветовой путь',observationIds:observations().map(o=>o.id),path,allowedQuestionableIds:state.allowed});
        state.path=path;state.transferId=t.id;invalidate();api.close();draw();App.toast('Цветовая траектория применена','success');
      } catch(e) {error.textContent=e.message;error.hidden=false;}
    }}]});
  }
  function questionable() {
    const records=knowledge().filter(k=>k.questionable && k.stage==='Производственное'),selected=new Set(state.allowed),error=h('p',{class:'field-error',role:'alert',hidden:true});
    App.modal({title:'Включить параметры под вопросом в этот план',body:h('div',{class:'stack'},h('p',{},'Разрешение действует только для текущего цветового плана. Стадия знания и флаг не изменятся.'),...records.map(k=>h('div',{class:'alert'},h('label',{class:'check'},h('input',{type:'checkbox',checked:selected.has(k.id),onChange:e=>e.target.checked?selected.add(k.id):selected.delete(k.id)}),swatch(k.lab),h('strong',{},labText(k.lab))),h('p',{},k.doubtReason || 'Параметры под вопросом'),h('p',{class:'text-sm'},'Наблюдения, вызвавшие сомнение: '+(k.doubtObservationIds || []).join(', ')),link('Наблюдения','/knowledge/'+encodeURIComponent(k.id)))),!records.length?h('p',{},'Нет производственных параметров под вопросом'):null,error),actions:[{label:'Отмена',onClick:api=>api.close()},{label:'Применить к этому плану',kind:'primary',onClick:api=>{
      try {
        if(state.planId) DB.allowQuestionable(state.planId,[...selected]);
        state.allowed=[...selected];generation++;failure=null;persist();api.close();draw();App.toast('Разрешение сохранено для текущего плана','success');
      } catch(e) {error.textContent=e.message;error.hidden=false;}
    }}]});
  }
  function demoArt() {
    const wrap=h('div',{class:'continuous-demo-art','aria-label':'Демонстрационная иллюстрация портрета'});
    wrap.innerHTML='<svg viewBox="0 0 320 340" role="img" aria-label="Демонстрационный портрет Анны"><rect width="320" height="340" fill="#dce1e7"/><path d="M20 340Q32 238 160 232Q283 238 303 340" fill="#555d69"/><path d="M91 153Q62 23 159 27Q265 29 239 161L226 228H94Z" fill="#303944"/><ellipse cx="164" cy="137" rx="67" ry="88" fill="#e5c6af"/><path d="M91 115Q90 30 166 30Q235 32 239 124Q215 81 174 70Q145 116 91 115" fill="#303944"/><path d="M135 150h13m37 0h13" stroke="#434247" stroke-width="5" stroke-linecap="round"/><path d="M166 157l-7 24h12m-25 18q18 13 36-1" fill="none" stroke="#aa7e6e" stroke-width="3"/><path d="M142 222v29q24 25 49 0v-29" fill="#d9b59c"/></svg>';
    return wrap;
  }
  function visual(image,layers,kind) {
    const wrap=h('div',{class:'continuous-visual'});
    if (!image) return h('div',{class:'continuous-visual continuous-placeholder'},'Добавьте фотографию для гравировки');
    if(!image.dataURL) {
      wrap.append(demoArt());
      if(kind==='brightness') wrap.classList.add('continuous-gray');
      if(kind==='bands' && layers?.length) wrap.append(h('div',{class:'continuous-demo-overlay'},...layers.map((l,i)=>h('div',{style:{background:rgb(l.lab),height:(100/layers.length)+'%'},title:'Полоса '+(i+1)+' · '+labText(l.lab)}))));
      wrap.append(h('span',{class:'continuous-caption'},kind==='bands'?'Демонстрационное квантование':'Демонстрационная иллюстрация'));
      return wrap;
    }
    const img=h('img',{src:image.dataURL,alt:kind==='brightness'?'Представление яркости исходной фотографии':'Исходная фотография для гравировки'});
    if(kind==='brightness')img.className='continuous-gray';
    wrap.append(img);
    if(kind==='bands' && layers?.length) {
      const canvas=h('canvas',{'aria-label':'Предпросмотр квантования фотографии в полосы',role:'img'});
      wrap.replaceChildren(canvas);
      const source=new Image();
      source.onload=()=>{
        try {
          const scale=Math.min(1,600/source.width,600/source.height);canvas.width=Math.max(1,Math.round(source.width*scale));canvas.height=Math.max(1,Math.round(source.height*scale));
          const c=canvas.getContext('2d');c.drawImage(source,0,0,canvas.width,canvas.height);const data=c.getImageData(0,0,canvas.width,canvas.height);
          const palette=layers.map(l=>rgb(l.lab).match(/\d+/g).map(Number));
          for(let i=0;i<data.data.length;i+=4) {
            const brightness=(0.2126*data.data[i]+0.7152*data.data[i+1]+0.0722*data.data[i+2])/255;
            const color=palette[Math.min(palette.length-1,Math.floor(brightness*palette.length))];
            data.data[i]=color[0];data.data[i+1]=color[1];data.data[i+2]=color[2];
          }
          c.putImageData(data,0,0);
        } catch (_) {wrap.replaceChildren(h('p',{class:'alert alert-danger'},'Не удалось прочитать изображение'));}
      };
      source.onerror=()=>wrap.replaceChildren(h('p',{class:'alert alert-danger'},'Не удалось прочитать изображение'));
      source.src=image.dataURL;
    }
    return wrap;
  }
  function upload(event) {
    const file=event.target.files?.[0];if(!file)return;
    action('Читаем фотографию…',()=>new Promise((resolve,reject)=>{
      const reader=new FileReader();
      reader.onerror=()=>reject(new Error('Не удалось прочитать изображение'));
      reader.onload=()=>{
        const img=new Image();
        img.onerror=()=>reject(new Error('Не удалось прочитать изображение'));
        img.onload=()=>{state.image={name:file.name,type:file.type,dataURL:reader.result,width:img.width,height:img.height};empty=false;invalidate();resolve();};
        img.src=reader.result;
      };
      if(!file.type.startsWith('image/')){reject(new Error('Не удалось прочитать изображение'));return;}
      reader.readAsDataURL(file);
    }));
  }
  function bandTable(p) {
    let selected=0;
    const detail=h('div',{class:'alert'}),table=h('table',{class:'table'});
    const body=h('tbody',{});
    function select(i) {
      selected=i;[...body.children].forEach((row,j)=>row.classList.toggle('selected',i===j));
      const l=p.layers[i],a=l.parameters;
      detail.replaceChildren(h('strong',{},'Полоса '+(i+1)),h('p',{},labText(l.lab)),h('p',{class:'text-sm'},`Полный вектор: мощность ${number(a.power)} %; частота ${number(a.frequency)} кГц; скорость ${number(a.speed)} мм/с; длительность импульса ${number(a.pulseDuration)} нс; интервал линий ${number(a.lineInterval)} мм; проходы ${number(a.passes)}.`),h('p',{class:'text-sm'},'Стадия: '+l.stage+(l.questionable?' · Под вопросом':'')),link('Запись знания','/knowledge/'+encodeURIComponent(l.knowledgeId)));
    }
    table.append(h('thead',{},h('tr',{},...['Полоса / яркость','Мощность, %','Частота, кГц','Скорость, мм/с','Прогноз Lab','Уверенность','Ошибка ΔE','Стабильность'].map(x=>h('th',{scope:'col'},x)))),body);
    p.layers.forEach((l,i)=>body.append(h('tr',{},h('td',{},button(String(i+1),()=>select(i),'btn-small'),h('div',{class:'text-sm'},(l.brightnessRange || [i/p.layers.length,(i+1)/p.layers.length]).map(number).join(' → '))),h('td',{},number(l.parameters.power)),h('td',{},number(l.parameters.frequency)),h('td',{},number(l.parameters.speed)),h('td',{},h('div',{class:'row'},swatch(l.lab),h('small',{},labText(l.lab)))),h('td',{},number(l.confidence),h('div',{class:'muted text-sm'},'Шкала 0–1')),h('td',{},number(l.expectedDeltaE)),h('td',{},l.stability?.assessed?'Оценена · разброс '+number(l.stability.variance):'Не оценена',l.questionable?h('div',{class:'badge badge-warning'},'Под вопросом'):null))));
    select(selected);
    return h('section',{class:'card stack'},h('h2',{},'Параметры полос · '+p.layers.length),h('p',{class:'muted'},'Каждая полоса — отдельный слой LightBurn с фиксированными параметрами. Значения демонстрационные.'),h('div',{class:'table-wrap'},table),detail);
  }
  function draw(loading) {
    if(!host)return;
    const profiles=all(E.profile),p=draft(),t=currentFunction(),image=empty?null:state.image;
    const n=Number(state.bandCount),validN=state.bandCount.trim()!=='' && Number.isSafeInteger(n) && n>0;
    const preview=!!(p?.previewSignature && p.layers?.length===n && p.transferId===state.transferId);
    const model=all(E.model).filter(m=>m.profileId===state.profileId).slice(-1)[0];
    const profileSelect=h('select',{disabled:busy || !profiles.length,onChange:e=>{state.profileId=e.target.value;state.transferId='';state.path=[];state.allowed=[];invalidate();draw();}},...profiles.map(p=>h('option',{value:p.id,selected:p.id===state.profileId},'Версия '+p.version+' · '+p.name)));
    const fnSelect=h('select',{disabled:busy || !functions().length,onChange:e=>{state.transferId=e.target.value;const t=currentFunction();state.path=t?.path || [];invalidate();draw();}},h('option',{value:'',selected:!state.transferId},'Выберите передаточную функцию'),...functions().map(t=>h('option',{value:t.id,selected:t.id===state.transferId},t.id+' · '+t.mode+' · '+t.observationIds.length+' наблюдений')));
    const bandsInput=h('input',{type:'number',min:'1',step:'1',value:state.bandCount,disabled:busy,'aria-describedby':'continuous-n-help',onInput:e=>{state.bandCount=e.target.value;invalidate();const error=document.getElementById('continuous-n-error');const v=Number(state.bandCount);const ok=state.bandCount.trim()!==''&&Number.isSafeInteger(v)&&v>0;error.hidden=ok;e.target.setAttribute('aria-invalid',String(!ok));host.querySelectorAll('[data-preview-action]').forEach(b=>b.disabled=!ok||busy||!image||!validFunction(currentFunction()));host.querySelectorAll('[data-create-action]').forEach(b=>b.disabled=true);const notice=host.querySelector('[data-stale]');if(notice)notice.hidden=false;},onChange:()=>draw()});
    const previewButton=button('Предпросмотр',()=>action('Рассчитываем полосы…',async()=>{const plan=ensureDraft();await DB.run('previewPhoto',plan.id);App.toast('Предпросмотр полос рассчитан','success');}),'',!image || !validN || !validFunction(t));previewButton.dataset.previewAction='';
    const createButton=button('Создать план',()=>action('Создаём план…',async()=>{const plan=await DB.run('finalizePhoto',state.planId);state.planId=null;state.allowed=[];persist();App.navigate('/plans/'+encodeURIComponent(plan.id));}),'btn-primary',!preview || !image || !validFunction(t));createButton.dataset.createAction='';
    const fileInput=h('input',{type:'file',accept:'image/*',class:'sr-only',disabled:busy,onChange:upload});
    const uploadButton=button('Выбрать фотографию',()=>fileInput.click());
    const settings=h('section',{class:'card stack'},h('h2',{},'Передаточная функция'),field('Версия профиля',profileSelect),h('p',{class:'muted text-sm'},'Версия модели: '+(model?.version || 'Нет модели')),field('Передаточная функция',fnSelect),h('div',{class:'row'},button('Калибровать по измерениям',calibrate,'',!profiles.length),state.mode==='Цветовой путь'?button('Выбрать траекторию',selectPath,'',!profiles.length):null),functionInfo(t),h('hr',{class:'divider'}),field('Число полос',bandsInput),h('p',{id:'continuous-n-help',class:'field-help'},'Положительное целое N. Демонстрационный сценарий: 32 полосы. Допустимый предел требует проверки версии LightBurn.'),h('p',{id:'continuous-n-error',class:'field-error',role:'alert',hidden:validN},'Введите положительное целое число полос'),h('label',{class:'check'},h('input',{type:'checkbox',checked:state.markers,disabled:busy,onChange:e=>{
      try {if(state.planId)DB.setPlanMarkers(state.planId,e.target.checked);state.markers=e.target.checked;persist();draw();}catch(error){App.toast(error.message,'error');draw();}
    }}),h('span',{},'Регистрационные маркеры')),h('p',{class:'field-help'},state.markers?'Маркеры и машинный идентификатор размещаются вне изображения. Идентификатор: '+(state.planId || 'Будет присвоен плану'):'Маркеры и идентификатор не включены.'),state.mode==='Цветовой путь'?button('Включить параметры под вопросом в этот план',questionable):null,state.mode==='Цветовой путь' && state.allowed.length?h('p',{class:'alert alert-warning'},'Разрешены для этого плана: '+state.allowed.join(', ')):null,h('div',{class:'form-actions'},previewButton,createButton));
    const warningIds=state.mode==='Тональный'?(preview?p.layers:((t?.points || []).map(point=>get(E.knowledge,point.knowledgeId)))).filter(k=>k?.questionable && k.stage==='Производственное').map(k=>k.knowledgeId || k.id):[];
    const warningObservations=[...new Set(warningIds.flatMap(id=>get(E.knowledge,id)?.doubtObservationIds || []))];
    const figures=h('section',{class:'card stack'},h('div',{class:'card-header'},h('div',{},h('h2',{},'Фотография и предпросмотр'),h('small',{class:'muted'},image?.name || 'Добавьте фотографию для гравировки')),uploadButton,fileInput),h('p',{class:'muted text-sm'},'Исходное изображение для гравировки не требует эталонной карты.'),h('div',{class:'continuous-images'},h('figure',{},h('figcaption',{},'Исходная фотография'),visual(image,null,'original')),h('figure',{},h('figcaption',{},'Яркость'),visual(image,null,'brightness')),h('figure',{},h('figcaption',{},'Предпросмотр полос'),preview?visual(image,p.layers,'bands'):h('div',{class:'continuous-visual continuous-placeholder'},'Рассчитайте предпрпросмотр полос'))),h('p',{class:'alert alert-warning',hidden:true,dataset:{stale:''}},'Число полос изменено. Пересчитайте предпросмотр перед созданием плана.'),preview?h('p',{class:'alert alert-success'},'Предпросмотр актуален · '+p.layers.length+' полос'):h('p',{class:'muted'},'Создание плана требует фотографии, калиброванной функции и актуального предпросмотра.'),state.mode==='Тональный'?h('p',{class:'text-sm'},'Тональный режим оценивается по яркости и контрасту.'):h('p',{class:'text-sm'},'Цветовой путь оценивается по ΔE вдоль траектории.'));
    host.replaceChildren(h('div',{class:'continuous-screen stack'},h('div',{class:'row'},h('div',{class:'segmented',role:'group','aria-label':'Подрежим фотогравировки'},...['Тональный','Цветовой путь'].map(mode=>h('button',{type:'button',class:'tab','aria-pressed':state.mode===mode,'aria-selected':state.mode===mode,disabled:busy,onClick:()=>{if(state.mode===mode)return;state.mode=mode;state.transferId='';state.path=[];state.allowed=[];invalidate();draw();}},mode))),h('span',{class:'spacer'}),link('Карта цветов','/colors?profileId='+encodeURIComponent(state.profileId))),loading?h('p',{class:'alert',role:'status'},loading):null,failure?h('div',{class:'alert alert-danger',role:'alert'},h('strong',{},'Не удалось рассчитать фотогравировку'),h('p',{},failure.message),button('Повторить',failure.retry)):null,!profiles.length?h('p',{class:'permission-restricted'},'Сначала настройте профиль лазера. ',link('Профили','/profiles')):null,warningIds.length?h('div',{class:'alert alert-warning'},h('strong',{},'Используются производственные параметры под вопросом'),h('p',{},'В тональном режиме отдельное подтверждение не требуется. Создание плана не изменяет флаг и стадию знания.'),button('Посмотреть наблюдения',()=>evidence(warningObservations,'Доказательства параметров под вопросом'))):null,h('div',{class:'continuous-layout'},figures,settings),preview?bandTable(p):null,h('details',{class:'continuous-assumptions'},h('summary',{},'Допущения экрана'),h('p',{},'Фотография хранится локально в черновике; для демонстрации подготовлена иллюстрация портрета. Предпросмотр квантования использует яркость пикселя и цвет выбранной полосы; он не моделирует физическую гравировку. Путь состоит из различных цветов, порядок меняется кнопками. Изменение режима или версии начинает отдельный черновик. Подбор и калибровка демонстрационные; точность и совместимость с LightBurn требуют проверки.'))));
  }
  App.addStyles('.continuous-layout{display:grid;grid-template-columns:minmax(0,1.5fr) minmax(310px,1fr);gap:24px;align-items:start}.continuous-images{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.continuous-images figure{margin:0;min-width:0}.continuous-images figcaption{font-size:13px;font-weight:600;margin-bottom:10px}.continuous-visual{position:relative;min-height:190px;background:#f0f2f5;border:1px solid var(--line);border-radius:12px;overflow:hidden;display:flex;align-items:center;justify-content:center}.continuous-visual img,.continuous-visual canvas{width:100%;height:auto;display:block}.continuous-placeholder{padding:24px;text-align:center;color:var(--muted);font-size:13px}.continuous-demo-art{width:100%}.continuous-demo-art svg{display:block;width:100%}.continuous-gray{filter:grayscale(1)}.continuous-demo-overlay{position:absolute;inset:0;mix-blend-mode:color;opacity:.85;pointer-events:none}.continuous-caption{position:absolute;bottom:0;left:0;right:0;padding:6px;background:#ffffffed;font-size:11px;text-align:center}.continuous-curve svg{width:100%;max-height:180px}.continuous-curve p{margin:0}.continuous-path-chip{display:flex;align-items:center;gap:8px}.continuous-observation-list{max-height:340px;overflow:auto;display:flex;flex-direction:column;gap:14px;padding:8px}.continuous-palette{display:flex;gap:8px;flex-wrap:wrap}.continuous-assumptions{color:var(--muted);font-size:13px;padding:16px}.continuous-assumptions summary{cursor:pointer}.continuous-assumptions p{margin:12px 0 0}.continuous-screen .field{margin-bottom:0}@media(max-width:1200px){.continuous-layout{grid-template-columns:1fr}.continuous-visual{min-height:240px}}@media(max-width:600px){.continuous-images{grid-template-columns:1fr}.continuous-visual{max-height:380px}.continuous-visual img,.continuous-visual canvas{max-height:380px;object-fit:contain}.continuous-demo-art{max-width:320px}.continuous-layout{gap:16px}}');
  App.register({id:'continuous',route:'/photo',title:'Непрерывная фотогравировка',render(ctx){
    const load=App.load(()=>{
      const requested=ctx.query.get('planId') || ctx.query.get('plan');
      const plan=requested?get(E.plan,requested):null;
      if(plan && ['Тональная фотогравировка','Фотогравировка по цветовому пути'].includes(plan.mode)) {
        state={...state,mode:plan.mode==='Тональная фотогравировка'?'Тональный':'Цветовой путь',profileId:plan.profileId,image:plan.image,bandCount:String(plan.bandCount || 32),transferId:plan.transferId || '',markers:plan.markers,path:get(E.function,plan.transferId)?.path || [],allowed:plan.allowedQuestionableIds || [],planId:plan.id};
      } else if(state.planId && !draft()) {state.planId=null;state.allowed=[];state.transferId='';state.image={name:'Анна-портрет.png',demo:true};state.bandCount='32';}
      const queryProfile=ctx.query.get('profileId');if(queryProfile && get(E.profile,queryProfile) && !requested && queryProfile!==state.profileId){state.profileId=queryProfile;state.transferId='';state.planId=null;state.path=[];state.allowed=[];}
      empty=ctx.proto.empty;
      if(empty){state={...state,image:null,planId:null,transferId:'',path:[],allowed:[]};}
      host=h('div',{});busy=false;failure=null;draw();return host;
    });
    const label=load.querySelector('.loading-label');if(label)label.textContent='Строим передаточную функцию…';
    return load;
  }});
})();
