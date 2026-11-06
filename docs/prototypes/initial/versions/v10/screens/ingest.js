(function () {
  'use strict';
  const h = App.h;
  const E = {pair:'Пара входных файлов',profile:'Профиль лазера',stand:'Установка съёмки',material:'Профиль материала',board:'Калибровочная плата'};
  const all = entity => DB.list(entity,{pageSize:10000,sort:'name',dir:'asc'}).items;
  const lab = v => v ? `Lab ${v.L.toFixed(1)} · ${v.a.toFixed(1)} · ${v.b.toFixed(1)}` : 'Не измерено';
  const labels = {power:'Мощность',frequency:'Частота',speed:'Скорость',pulseDuration:'Длительность импульса',lineInterval:'Интервал линий',passes:'Проходы'};
  const units = {power:'%',frequency:'кГц',speed:'мм/с',pulseDuration:'нс',lineInterval:'мм',passes:''};
  const button = (text,fn,primary=false,disabled=false) => h('button',{type:'button',class:'btn'+(primary?' btn-primary':''),disabled,onClick:fn},text);
  const link = (text,path) => h('a',{href:'#'+path,class:'btn'},text);
  const notice = (text,kind='warning') => h('div',{class:'alert alert-'+kind,role:kind==='danger'?'alert':'status'},text);
  const vector = p => h('dl',{class:'ing-vector'},Object.keys(labels).map(k=>[h('dt',{},labels[k]),h('dd',{},p?.[k] == null ? 'Неизвестно' : `${p[k]} ${units[k]}`)]));
  App.addStyles(`.ingest{display:flex;flex-direction:column;gap:24px}.ing-top{display:grid;grid-template-columns:1fr 1fr;gap:20px}.ing-upload{border:1px dashed #b9c9dc;border-radius:14px;padding:22px;background:#fafcff}.ing-upload h2{margin-bottom:8px}.ing-upload p{overflow-wrap:anywhere}.ing-photo{position:relative;aspect-ratio:1.45;background:linear-gradient(135deg,#cbd0d5,#edf0f2 38%,#bbc2ca);border:1px solid #adb5c0;border-radius:12px;overflow:hidden;touch-action:none;min-height:240px}.ing-photo:before{content:'';position:absolute;inset:15% 10%;border:1px solid #8994a2;background:linear-gradient(100deg,#b8bcc4,#e0e3e7,#bfc8d0);box-shadow:0 5px 16px #0002}.ing-regions{position:absolute;inset:26% 15% 30%;display:flex;gap:4px;align-items:stretch}.ing-region{flex:1;min-width:0;border:2px solid transparent;border-radius:3px;opacity:.8;padding:2px;color:#18202b;font-size:11px;overflow:hidden}.ing-region[aria-pressed=true]{outline:3px solid #0066d6;outline-offset:3px;z-index:2}.ing-region.mask{border:2px dashed #fff;box-shadow:inset 0 0 0 2px #0066d6}.ing-reference{position:absolute;bottom:8%;left:12%;display:grid;grid-template-columns:repeat(6,1fr);width:40%;gap:2px;padding:4px;background:#242832}.ing-reference span{height:16px}.ing-tag{position:absolute;top:10px;left:10px;padding:4px 9px;border-radius:6px;background:#fffffff0;font-size:12px}.ing-point{position:absolute;width:30px;height:30px;margin:-15px;border-radius:50%;border:2px solid white;background:#0066d6;color:white;font-weight:700;z-index:5;padding:0;box-shadow:0 1px 8px #0005;cursor:move}.ing-vector{display:grid;grid-template-columns:1fr 1fr;gap:7px 14px;margin:12px 0;font-size:13px}.ing-vector dt{color:var(--muted)}.ing-vector dd{margin:0;text-align:right}.ing-status{font-size:13px;color:var(--muted)}.ing-checks{display:flex;flex-direction:column;gap:12px}.ing-checks p{margin:0}.ing-context{padding-top:18px}.ingest details>summary{cursor:pointer;font-weight:600;padding:8px 0}.ingest .table{min-width:700px}.ing-layer{border-top:1px solid var(--line);padding-top:16px}.ing-photo-pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}.ing-photo-pair .ing-photo{min-height:180px}.ing-photo.before{filter:saturate(.65)}.ing-corner-list{display:grid;grid-template-columns:1fr 1fr;gap:10px}.ing-corner-list .field{margin:0}.ingest .ing-error{margin:8px 0;color:var(--danger)}@media(max-width:700px){.ing-top,.ing-photo-pair,.ing-corner-list{grid-template-columns:1fr}.ing-upload{padding:18px}.ing-vector{grid-template-columns:1fr 1fr}.ing-photo{min-height:230px}}`);
  App.register({id:'ingest',route:'/ingest',title:'Добавить наблюдение',render(ctx){
    const host = App.load(()=>build(ctx));
    const loading = host.querySelector('.loading-label');
    if(loading) loading.textContent='Читаем слои и проверки пары…';
    return host;
  }});
  function build(ctx) {
    const profiles=all(E.profile), stands=all(E.stand), materials=all(E.material);
    const requested=ctx.query.get('pair')||ctx.query.get('pairId')||ctx.query.get('id');
    let pair=ctx.proto.empty?null:(requested?DB.get(E.pair,requested):null);
    let selected=null, showMasks=true, corrected=true, busy=false, pendingRetry=null;
    let points=(pair?.alignment?.points||[]).map(p=>({...p}));
    let cornerIndex=points.length<4?points.length:0;
    let scenario={referenceDetected:true,markersValid:true,hasMarkers:true};
    let fileErrors={}, operationError='', success='', formErrors={};
    const root=h('div',{class:'ingest'});
    const values={profileId:pair?.profileId||profiles[0]?.id||'',standId:pair?.standId||stands[0]?.id||'',context:{...(pair?.context||{})}};
    const storageKey='titanium.ingest.draft.v1';
    if(!pair&&!ctx.proto.empty) {
      try {const stored=JSON.parse(localStorage.getItem(storageKey)||'null');if(stored){const found=DB.get(E.pair,stored.pairId);if(found&&found.status!=='Принята'){pair=found;values.profileId=found.profileId||values.profileId;values.standId=found.standId||values.standId;values.context={...found.context};points=(found.alignment?.points||[]).map(p=>({...p}));}}}catch(_){}
    }
    const remember=()=>{try{localStorage.setItem(storageKey,JSON.stringify({pairId:pair?.id||null}));}catch(_){App.toast('Черновик доступен до закрытия страницы','warning');}};
    const errorText=e=>e?.message||'Не удалось выполнить проверку';
    async function action(fn,loading,after) {
      if(busy)return;
      busy=true;operationError='';pendingRetry=null;paint(loading);
      try {const result=await fn();if(result?.id)pair=result;remember();success='';if(after)await after(result);}
      catch(e){operationError=errorText(e);pendingRetry=()=>action(fn,loading,after);}
      finally{busy=false;if(root.isConnected)paint();}
    }
    function ensurePair() {
      if(pair)return pair;
      pair=DB.create(E.pair,{name:'Новая пара — измерение титана',profileId:values.profileId||null,standId:values.standId||null,context:values.context,planId:ctx.query.get('plan')||ctx.query.get('planId')||null});
      remember();return pair;
    }
    function saveContext() {
      if(!pair)return;
      pair=DB.update(E.pair,pair.id,{profileId:values.profileId||null,standId:values.standId||null,context:{...values.context}});remember();
    }
    const ready=()=>!!(pair&&pair.status==='Готова к принятию'&&pair.lightburnFile&&pair.photo&&pair.profileId&&pair.standId&&pair.reference?.detected&&pair.reference?.corrected&&pair.alignment?.valid&&pair.masksReviewed&&(!pair.discrepancies?.length||pair.fileConfirmation)&&pair.layers?.some(l=>l.readable!==false&&l.compatible!==false));
    function field(title,key,value,onInput,options={}) {
      const id='ing-'+key;
      const input=h(options.select?'select':options.multiline?'textarea':'input',{id,class:options.select?'select':'input',type:options.type||'text',value:value??'',disabled:busy||pair?.status==='Принята',...(options.type==='number'?{step:'any'}:{}),onChange:e=>{onInput(e.target.value);},'aria-describedby':id+'-help'});
      if(options.select){input.append(h('option',{value:''},'Выберите значение'));options.select.forEach(o=>input.append(h('option',{value:o.id,selected:o.id===value},o.label||o.name)));input.value=value||'';}
      return h('div',{class:'field'+(formErrors[key]?' has-error':'')},h('label',{for:id},title),input,h('span',{id:id+'-help',class:formErrors[key]?'field-error':'field-help'},formErrors[key]||options.help||''));
    }
    function changeValue(key,v){
      values[key]=v;formErrors={};operationError='';
      try{saveContext();points=(pair?.alignment?.points||[]).map(p=>({...p}));}catch(e){operationError=errorText(e);}
      paint();
    }
    function contextValue(key,v){
      const previous=values.context[key];
      values.context[key]=v;
      try{saveContext();formErrors[key]='';}catch(e){values.context[key]=previous;formErrors[key]=errorText(e);}
      const error=root.querySelector('#ing-'+key+'-help');if(error){error.textContent=formErrors[key]||'Необязательно · пустое значение: «Неизвестно»';error.className=formErrors[key]?'field-error':'field-help';}
    }
    async function upload(kind,file) {
      if(!file)return;
      const good=kind==='lightburnFile'?/\.(lbrn|lbrn2)$/i.test(file.name):/\.(raw|nef|nrw|cr2|cr3|arw|dng|raf|rw2|orf|pef|srw)$/i.test(file.name);
      fileErrors[kind]=good?'':kind==='lightburnFile'?'Выберите файл .lbrn или .lbrn2':'Для измерения требуется фотография RAW';
      if(!good){paint();return;}
      await action(async()=>{
        const p=ensurePair();
        const attached=await DB.run('attachFiles',p.id,{[kind]:{name:file.name,size:file.size}});
        pair=attached;points=[];selected=null;
        if(attached.lightburnFile&&attached.photo&&attached.profileId&&attached.standId)return checks();
        return attached;
      },kind==='lightburnFile'?'Читаем слои…':'Ищем эталон…');
    }
    async function checks() {
      let result=await DB.run('checkPair',pair.id,scenario);
      pair=result;
      if(result.status==='Ошибка')return result;
      paint('Выравниваем фотографию…');
      await new Promise(resolve=>setTimeout(resolve,220));
      paint('Измеряем области…');
      await new Promise(resolve=>setTimeout(resolve,220));
      points=(result.alignment?.points||[]).map(p=>({...p}));selected=result.layers?.[0]?.id||null;
      return result;
    }
    function uploadCard(kind,title,accept) {
      const info=pair?.[kind];
      const input=h('input',{type:'file',accept,id:'ing-file-'+kind,class:'sr-only',disabled:busy||pair?.status==='Принята',onChange:e=>upload(kind,e.target.files[0])});
      return h('section',{class:'ing-upload'},h('h2',{},title),h('p',{class:'muted'},info?`${info.name}${info.size?' · '+Math.round(info.size/1024)+' КБ':''}`:'Файл не выбран'),input,button(kind==='photo'?'Выбрать фотографию':'Выбрать файл LightBurn',()=>input.click(),false,busy||pair?.status==='Принята'),h('p',{class:'field-help'},kind==='photo'?'RAW со фиксированного стенда; эталонная карта обязательна.':'.lbrn или .lbrn2 · параметры читаются из файла'),fileErrors[kind]?h('p',{class:'field-error',role:'alert'},fileErrors[kind]):null,h('span',{class:'ing-status'},busy?'Проверяется':info?'Локальный файл выбран':'Ожидает файла'));
    }
    function photo(before=false,manual=false) {
      const panel=h('div',{class:'ing-photo'+(before?' before':''),'aria-label':before?'Демонстрационная фотография до коррекции':'Демонстрационная фотография после коррекции'});
      panel.append(h('span',{class:'ing-tag'},before?'До коррекции · демонстрация':'После коррекции · демонстрация'));
      const strips=h('div',{class:'ing-regions'});
      (pair?.layers||[]).forEach((l,i)=>strips.append(h('button',{type:'button',class:'ing-region'+(!before&&showMasks?' mask':''),style:{background:['#c4a34f','#ad7785','#916aab','#577bad','#619fa0','#9aa669'][i%6]},'aria-label':'Область '+l.regionId,'aria-pressed':selected===l.id,disabled:busy,onClick:e=>{e.stopPropagation();selected=l.id;paint();}},l.regionId)));
      panel.append(strips);
      if(pair?.reference?.detected)panel.append(h('div',{class:'ing-reference','aria-label':'Обнаруженная эталонная карта'},['#8c6358','#c29e82','#55708e','#657451','#b8809c','#72aeb1','#fff','#d5d5d5','#aaa','#777','#454545','#222'].map(c=>h('span',{style:{background:c}}))));
      if(pair?.alignment?.method==='По маркерам')panel.append(h('span',{style:{position:'absolute',right:'10%',top:'15%',fontSize:'24px'},'aria-label':'Регистрационный маркер'},'⊕'));
      if(manual) {
        panel.setAttribute('tabindex','0');
        panel.setAttribute('aria-label','Установка углов. Нажмите на фотографию или используйте числовые координаты под ней.');
        panel.addEventListener('click',e=>{
          if(busy||e.target.closest('button'))return;
          const rect=panel.getBoundingClientRect();
          points[cornerIndex]={x:Math.max(0,Math.min(100,(e.clientX-rect.left)/rect.width*100)),y:Math.max(0,Math.min(100,(e.clientY-rect.top)/rect.height*100))};
          invalidateCorners();cornerIndex=Math.min(3,cornerIndex+1);paint();
        });
        points.forEach((p,i)=>{
          if(!p)return;
          const dot=h('button',{type:'button',class:'ing-point',style:{left:p.x+'%',top:p.y+'%'},'aria-label':`${i+1}. ${cornerNames[i]}. Стрелки изменяют координаты.`,onClick:e=>e.stopPropagation(),onKeydown:e=>{
            const d={ArrowLeft:[-1,0],ArrowRight:[1,0],ArrowUp:[0,-1],ArrowDown:[0,1]}[e.key];if(!d)return;e.preventDefault();p.x=Math.max(0,Math.min(100,p.x+d[0]));p.y=Math.max(0,Math.min(100,p.y+d[1]));invalidateCorners();dot.style.left=p.x+'%';dot.style.top=p.y+'%';syncCoordinates(i);
          }},i+1);
          dot.addEventListener('pointerdown',e=>{if(busy)return;e.preventDefault();dot.setPointerCapture(e.pointerId);});
          dot.addEventListener('pointermove',e=>{if(!dot.hasPointerCapture(e.pointerId))return;const r=panel.getBoundingClientRect();p.x=Math.max(0,Math.min(100,(e.clientX-r.left)/r.width*100));p.y=Math.max(0,Math.min(100,(e.clientY-r.top)/r.height*100));invalidateCorners();dot.style.left=p.x+'%';dot.style.top=p.y+'%';syncCoordinates(i);});
          dot.addEventListener('pointerup',e=>{dot.releasePointerCapture(e.pointerId);rememberCorners();});
          panel.append(dot);
        });
      }
      return panel;
    }
    const cornerNames=['Верхний левый','Верхний правый','Нижний правый','Нижний левый'];
    function invalidateCorners(){
      if(pair?.alignment?.valid){try{pair=DB.resetCorners(pair.id);}catch(e){operationError=errorText(e);}}
      const accept=root.querySelector('[data-accept]');if(accept)accept.disabled=true;
      const review=root.querySelector('[data-review]');if(review){review.checked=false;review.disabled=true;}
    }
    function rememberCorners(){try{localStorage.setItem('titanium.ingest.corners.'+pair.id,JSON.stringify(points));}catch(_){} }
    if(pair&&pair.alignment?.method==='По углам'&&!pair.alignment.valid){try{const cached=JSON.parse(localStorage.getItem('titanium.ingest.corners.'+pair.id)||'null');if(Array.isArray(cached))points=cached;}catch(_){}}
    function syncCoordinates(i){['x','y'].forEach(k=>{const input=root.querySelector('#ing-point-'+i+'-'+k);if(input)input.value=points[i][k].toFixed(1);});rememberCorners();}
    function cornerControls() {
      const fields=h('div',{class:'ing-corner-list'});
      cornerNames.forEach((name,i)=>fields.append(h('div',{class:'field'},h('label',{},`${i+1}. ${name}`),button(cornerIndex===i?'Следующая точка на фото':'Установить на фото',()=>{cornerIndex=i;paint();},false,busy),h('div',{class:'row'},['x','y'].map(k=>h('label',{class:'field',style:{flex:'1'}},k==='x'?'По горизонтали, %':'По вертикали, %',h('input',{id:'ing-point-'+i+'-'+k,type:'number',min:0,max:100,step:'0.1',value:points[i]?.[k]??'',disabled:busy,onChange:e=>{
        if(e.target.value===''||!Number.isFinite(Number(e.target.value))||Number(e.target.value)<0||Number(e.target.value)>100){formErrors.corners='Укажите четыре угла изображения по порядку';paint();return;}
        if(!points[i])points[i]={x:50,y:50};points[i][k]=Number(e.target.value);invalidateCorners();rememberCorners();paint();
      }})))))));
      return h('div',{class:'stack'},h('p',{class:'field-help'},'Укажите углы по порядку. Точки можно перетаскивать; стрелки на выбранной точке сдвигают её на 1%. Координаты нормированы к демонстрационному изображению.'),fields,formErrors.corners?h('p',{class:'field-error',role:'alert'},formErrors.corners):null,h('div',{class:'row'},button('Применить выравнивание',()=>action(async()=>{
        try{const result=await DB.run('applyCorners',pair.id,points);formErrors.corners='';return result;}catch(e){formErrors.corners='Укажите четыре угла изображения по порядку';throw e;}
      },'Выравниваем фотографию…'),true,busy),button('Сбросить углы',()=>action(()=>DB.run('resetCorners',pair.id),'Сбрасываем углы…',()=>{points=[];cornerIndex=0;rememberCorners();}),false,busy)));
    }
    function discrepancyTable(rows) {
      return h('div',{class:'table-wrap'},h('table',{class:'table'},h('thead',{},h('tr',{},['Ячейка','Поле','Определение платы','Файл LightBurn','Разрешение'].map(t=>h('th',{},t)))),h('tbody',{},rows.map(d=>h('tr',{},h('td',{},d.cellId),h('td',{},labels[d.field]||d.field),h('td',{},d.defined),h('td',{},d.fromFile),h('td',{},pair.fileConfirmation?'Использованный файл подтверждён':'Ожидает подтверждения'))))));
    }
    function confirmFile() {
      let checked=false;
      const checkbox=h('input',{type:'checkbox',onChange:e=>{checked=e.target.checked;api.element.querySelector('.modal-actions .btn-primary').disabled=!checked;}});
      const api=App.modal({title:'Подтвердить использованный файл',body:h('div',{class:'stack'},discrepancyTable(pair.discrepancies),h('label',{class:'check'},checkbox,h('span',{},'Подтверждаю, что приложенный файл LightBurn использовался для физической гравировки'))),actions:[{label:'Отмена',onClick:a=>a.close()},{label:'Подтвердить',kind:'primary',disabled:true,onClick:async a=>{
        try{pair=await DB.run('confirmUsedFile',pair.id,checked);remember();a.close();App.toast('Использованный файл подтверждён','success');paint();}catch(e){App.toast(errorText(e),'error');}
      }}]});
    }
    function layerTable(){
      return h('div',{class:'table-wrap'},h('table',{class:'table'},h('thead',{},h('tr',{},['Слой и область','Мощность','Частота','Скорость','Геометрия заливки','Проверка'].map(t=>h('th',{},t)))),h('tbody',{},pair.layers.map(l=>h('tr',{class:selected===l.id?'selected':''},h('td',{},button(l.id,()=>{selected=l.id;paint();},false,busy),h('small',{class:'muted'},l.regionId)),['power','frequency','speed'].map(k=>h('td',{},l.readable===false?'Не прочитано':`${l.parameters?.[k]??'Неизвестно'} ${units[k]}`)),h('td',{},l.geometry?`Заливка ${l.geometry.width} × ${l.geometry.height}; начало ${l.geometry.x}, ${l.geometry.y}`:'Геометрия отсутствует'),h('td',{},l.readable===false?'Параметры слоя не удалось прочитать':l.compatible===false?'Неподдерживаемые параметры профиля · Несопоставимо с активным профилем':'Параметры прочитаны · Совместимо'))))));
    }
    function paint(loading) {
      root.replaceChildren();
      root.append(h('div',{class:'row'},link('Назад к экспериментам','/experiments'),h('span',{class:'spacer'}),pair?h('span',{class:'badge'},pair.status):h('span',{class:'badge'},'Ожидает файлов')));
      if(pair)root.append(h('div',{class:'row'},h('button',{type:'button',class:'btn btn-danger',disabled:busy,onClick:()=>App.removeRecord(E.pair,pair,()=>{
        try{localStorage.removeItem(storageKey);}catch(_){}
        App.navigate('/experiments');
      })},'Удалить пару')));
      if(requested&&!pair&&!ctx.proto.empty)root.append(notice('Пара входных файлов не найдена. Можно добавить новую пару.','danger'));
      if(!pair)root.append(h('section',{class:'empty-state'},h('h2',{},'Добавьте файл LightBurn и фотографию со стенда'),h('p',{},'Параметры наблюдения будут прочитаны из фактически использованного файла. Измерения появятся только после проверки и принятия.')));
      if(pair?.status==='Принята') {
        root.append(notice('Наблюдения приняты. Пара файлов и измеренный цвет неизменяемы.','success'),link('Открыть анализ','/analysis/'+encodeURIComponent(pair.id)));
      }
      if(loading)root.append(notice(loading,'success'));
      if(operationError)root.append(h('div',{class:'alert alert-danger',role:'alert'},h('p',{},operationError),pendingRetry?button('Повторить проверку',pendingRetry,false,busy):null));
      if(success)root.append(notice(success,'success'));
      root.append(h('div',{class:'ing-top'},uploadCard('lightburnFile','Файл LightBurn','.lbrn,.lbrn2'),uploadCard('photo','Фотография со стенда','.raw,.nef,.nrw,.cr2,.cr3,.arw,.dng,.raf,.rw2,.orf,.pef,.srw')));
      const setup=h('section',{class:'card'},h('h2',{},'Контекст измерения'),h('div',{class:'grid'},field('Профиль лазера','profileId',values.profileId,v=>changeValue('profileId',v),{select:profiles.map(p=>({...p,label:`${p.name} · версия ${p.version}`})),help:'Обязательная версия. Константы берутся из профиля.'}),field('Стенд','standId',values.standId,v=>changeValue('standId',v),{select:stands,help:'Обязательная установка съёмки · RAW'})));
      if(!profiles.length||!stands.length)setup.append(notice('Сначала настройте профиль лазера и стенд'),link('Настроить профили','/profiles'));
      const stand=values.standId?DB.get(E.stand,values.standId):null;
      if(stand)setup.append(h('p',{class:'field-help'},`${stand.camera} · ${stand.lighting} · Угол: ${stand.angle} · ${stand.referenceCard} · RAW`));
      const details=h('details',{class:'ing-context',open:!!Object.values(values.context).some(v=>v!==null&&v!==undefined&&v!=='')},h('summary',{},'Дополнительный контекст'));
      details.append(h('p',{class:'field-help'},'Необязательные значения не блокируют принятие и не снижают допуск к независимым повторам.'),button('Как у предыдущей платы',()=>{try{values.context=DB.previousContext(values.profileId);saveContext();paint();App.toast('Доступный предыдущий контекст подставлен');}catch(e){operationError=errorText(e);paint();}},false,busy||pair?.status==='Принята'),h('div',{class:'grid',style:{marginTop:'16px'}},field('Материал','materialId',values.context.materialId,v=>contextValue('materialId',v||null),{select:materials,help:'Необязательно · Неизвестно'}),field('Партия или лист','batch',values.context.batch,v=>contextValue('batch',v||null),{help:'Необязательно · Неизвестно'}),field('Фокус','focus',values.context.focus,v=>contextValue('focus',v===''?null:Number(v)),{type:'number',help:'Необязательно · единица фокуса требованиями не определена'}),field('Дата гравировки','engravedAt',values.context.engravedAt,v=>contextValue('engravedAt',v||null),{type:'date',help:'Необязательно · Неизвестно'})),field('Примечание','note',values.context.note,v=>contextValue('note',v),{multiline:true,help:'Необязательно · Неизвестно'}));
      setup.append(details);root.append(setup);
      const canCheck=pair?.lightburnFile&&pair?.photo&&values.profileId&&values.standId&&pair.status!=='Принята';
      if(pair&&pair.status!=='Принята')root.append(button('Повторить проверку',()=>action(checks,'Читаем слои…'),false,busy||!canCheck));
      if(pair?.error)root.append(notice(pair.error,'danger'));
      if(pair?.reference&&!pair.reference.detected)root.append(notice('Эталонная карта не обнаружена. Наблюдения не будут созданы','danger'));
      if(pair?.layers?.length) {
        const manual=pair.alignment?.method==='По углам'&&pair.status!=='Принята';
        const main=h('section',{class:'card stack'},h('div',{class:'card-header'},h('h2',{},'Фотография и маски слоёв'),h('span',{class:'badge'},pair.alignment?.method||'Не выровнено')));
        main.append(h('div',{class:'row'},button(corrected?'Показать до коррекции':'Показать после коррекции',()=>{corrected=!corrected;paint();},false,busy),h('label',{class:'check'},h('input',{type:'checkbox',checked:showMasks,disabled:busy,onChange:e=>{showMasks=e.target.checked;paint();}}),'Показать маски слоёв')));
        main.append(photo(!corrected,manual));
        if(manual)main.append(cornerControls());
        const selectedLayer=pair.layers.find(l=>l.id===selected)||pair.layers[0];selected=selectedLayer.id;
        main.append(h('div',{class:'ing-layer'},h('h3',{},'Область '+selectedLayer.regionId),h('p',{},lab(selectedLayer.measuredLab)),vector(selectedLayer.parameters),h('p',{class:'field-help'},'Параметры файла и константы профиля — только для чтения. Цвет измеряется внутри маски; края исключены. Размер исключаемого края требованиями не определён.')));
        const check=h('aside',{class:'card ing-checks'},h('h2',{},'Проверки перед принятием'),h('p',{},'Эталон: '+(pair.reference?.detected?'обнаружен':'не обнаружен')),h('p',{},'Коррекция: '+(pair.reference?.corrected?'выполнена':'не выполнена')),h('p',{},'Выравнивание: '+(pair.alignment?.valid?'проверено':'укажите четыре угла')),pair.boardId?h('p',{},'Маркеры и машинный идентификатор: '+(pair.alignment?.machineIdVerified?'проверены':'сопоставление остановлено')):null);
        const model=DB.metrics(pair.profileId).model;
        const eligible=!!(pair.reference?.corrected&&pair.alignment?.valid&&selectedLayer.readable!==false&&selectedLayer.compatible!==false);
        check.append(h('h3',{},'Допуск к модели'),h('p',{},eligible?'Допускается: эталон, параметры и выравнивание проверены':'Не допускается: область не соответствует условиям измерения'),h('h3',{},'Допуск к независимым повторам'),h('p',{},!model?.rules?.agreed?'Допуск к независимым повторам ещё не определён':!eligible?'Не допускается: область не соответствует условиям измерения':pair.independence?.confirmed?'Допускается: отдельное физическое изделие подтверждено':'Не допускается: независимость физической гравировки не подтверждена'),h('p',{class:'field-help'},'Эталон не доказывает независимость. Повторная фотография того же изделия оценивает повторяемость стенда.'));
        if(pair.status!=='Принята') {
          check.append(h('label',{class:'check'},h('input',{type:'checkbox',checked:!!pair.independence?.confirmed,disabled:busy||!!pair.repeatOfPairId,onChange:e=>action(()=>DB.run('confirmIndependentEngraving',pair.id,e.target.checked),'Сохраняем контекст повтора…')}),'Отдельная независимая гравировка на новом изделии'),h('label',{class:'check'},h('input',{type:'checkbox',dataset:{review:'true'},checked:!!pair.masksReviewed,disabled:busy||!pair.alignment?.valid,onChange:e=>action(()=>DB.run('reviewMasks',pair.id,e.target.checked),'Сохраняем проверку масок…')}),'Маски слоёв проверены: области и исключённые края соответствуют фотографии'));
          if(pair.repeatOfPairId)check.append(notice('Повторная фотография этого изделия не является независимой гравировкой'));
        }
        root.append(h('div',{class:'split'},main,check),h('section',{class:'card stack'},h('h2',{},'Разобранные слои'),layerTable()));
      }
      if(pair?.discrepancies?.length)root.append(h('section',{class:'card stack'},h('h2',{},'Сравнение с определением платы'),notice('Параметры файла отличаются от определения платы. Исправьте пару или подтвердите использованный файл'),discrepancyTable(pair.discrepancies),pair.fileConfirmation?h('p',{class:'field-help'},`${pair.fileConfirmation.text} · ${new Date(pair.fileConfirmation.at).toLocaleString('ru-RU')}`):h('div',{class:'row'},button('Исправить пару',()=>{root.querySelector('#ing-file-lightburnFile').click();},false,busy),button('Подтвердить использованный файл',confirmFile,false,busy))));
      if(pair?.status!=='Принята') {
        const reasons=[];
        if(!pair?.lightburnFile||!pair?.photo)reasons.push('Добавьте оба файла');
        if(!values.profileId||!values.standId)reasons.push('Выберите профиль и стенд');
        if(pair?.layers?.length&&!pair?.masksReviewed)reasons.push('Проверьте маски слоёв перед принятием');
        if(pair?.layers?.length&&!pair?.alignment?.valid)reasons.push('Примените выравнивание');
        if(pair?.discrepancies?.length&&!pair.fileConfirmation)reasons.push('Разрешите расхождения платы');
        const accept=button('Принять наблюдения',()=>action(()=>DB.run('acceptObservations',pair.id),'Сохраняем наблюдения…',result=>{try{localStorage.removeItem(storageKey);}catch(_){}App.toast('Наблюдения приняты','success');App.navigate('/analysis/'+encodeURIComponent(result.pair.id));}),true,busy||!ready());accept.dataset.accept='true';
        root.append(h('section',{class:'card'},h('div',{class:'row'},accept,h('span',{class:'field-help'},ready()?'Проверьте маски слоёв перед принятием':reasons.join(' · ')||'Завершите успешную проверку эталона, параметров и выравнивания'))));
      }
      const demo=h('details',{},h('summary',{},'Демонстрационные сценарии и допущения'),h('p',{class:'field-help'},'Файлы остаются локальными. Прототип сохраняет метаданные, а разбор RAW, цветовая коррекция и измерения демонстрируются подготовленными результатами. Изображение на экране — условная схема фотографии, а не содержимое RAW. Форматы RAW и координаты в процентах выбраны для демонстрации. Независимость отдельной гравировки подтверждается явно согласно контракту DB.'),h('p',{class:'field-help'},'Ролевых ограничений нет: единственный исследователь имеет все права. Принятие блокируют только проверки готовности данных. Демонстрационные переключатели ниже применяются при повторной проверке.'));
      [['referenceDetected','Эталонная карта обнаружена'],['hasMarkers','На готовой работе есть маркеры'],['markersValid','Маркеры и идентификатор платы распознаны']].forEach(([key,title])=>demo.append(h('label',{class:'check'},h('input',{type:'checkbox',checked:scenario[key],disabled:busy||pair?.status==='Принята'||(key==='hasMarkers'&&!!pair?.boardId),onChange:e=>{scenario[key]=e.target.checked;}}),title)));
      demo.append(h('p',{class:'field-help'},'Чтобы проверить сценарий, нажмите «Повторить проверку». Для платы ручное выравнивание не предлагается. Нечитаемые или несопоставимые области никогда не превращаются в наблюдения с придуманными параметрами.'));
      root.append(demo);
    }
    paint();return root;
  }
})();
