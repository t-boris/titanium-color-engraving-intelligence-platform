(function () {
  'use strict';
  const h = App.h;
  const entities = { pair:'Пара входных файлов', observation:'Наблюдение', report:'Отчёт после гравировки', plan:'План гравировки', profile:'Профиль лазера', knowledge:'Запись знания', model:'Модель цветового пространства', material:'Профиль материала', stand:'Установка съёмки' };
  const all = (entity, filter) => DB.list(entity,{filter:filter || {},pageSize:100000,sort:'createdAt',dir:'asc'}).items;
  const n = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ru-RU',{maximumFractionDigits:3}) : 'Нет исходных данных';
  const lab = value => value ? `Lab ${n(value.L)} · ${n(value.a)} · ${n(value.b)}` : 'Плановый цвет отсутствует';
  const link = (label, route) => h('a',{href:'#'+route},label);
  const path = (route,id) => route+'/'+encodeURIComponent(id);
  const date = value => value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString('ru-RU') : 'Неизвестно';
  const button = (label, action, primary) => h('button',{type:'button',class:'btn'+(primary?' btn-primary':''),onClick:action},label);
  const unknown = value => value === null || value === undefined || value === '' ? 'Неизвестно' : String(value);
  function color(value) {
    if (!value) return '#e7e9ee';
    const fy=(value.L+16)/116, fx=fy+value.a/500, fz=fy-value.b/200;
    const inverse=t=>t*t*t>0.008856?t*t*t:(t-16/116)/7.787;
    const x=inverse(fx)*0.95047,y=inverse(fy),z=inverse(fz)*1.08883;
    const channel=t=>Math.round(255*Math.min(1,Math.max(0,t<=0.0031308?12.92*t:1.055*Math.pow(t,1/2.4)-0.055)));
    return `rgb(${channel(3.2406*x-1.5372*y-0.4986*z)},${channel(-0.9689*x+1.8758*y+0.0415*z)},${channel(0.0557*x-0.204*y+1.057*z)})`;
  }
  function swatch(value) { return h('span',{class:'swatch',style:{background:color(value)},'aria-hidden':'true'}); }
  function definition(rows) { return h('dl',{class:'analysis-definition'},rows.map(([label,value])=>[h('dt',{},label),h('dd',{},value)])); }
  function vector(p) {
    p=p||{};
    return definition([['Мощность',n(p.power)+' %'],['Частота',n(p.frequency)+' кГц'],['Скорость',n(p.speed)+' мм/с'],['Длительность импульса',n(p.pulseDuration)+' нс'],['Интервал линий',n(p.lineInterval)+' мм'],['Проходы',n(p.passes)]]);
  }
  App.addStyles(`.analysis-screen{display:flex;flex-direction:column;gap:24px}.analysis-screen .toolbar{margin:0}.analysis-visuals{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.analysis-visual{background:#f8f9fb;border:1px solid var(--line);border-radius:12px;padding:16px;min-width:0}.analysis-visual h3{font-size:14px}.analysis-regions{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;min-height:160px}.analysis-region{border:2px solid transparent;border-radius:8px;min-height:66px;padding:8px;position:relative}.analysis-region[aria-pressed=true]{border-color:var(--accent);box-shadow:0 0 0 2px white,0 0 0 4px var(--accent)}.analysis-region span{display:inline-block;padding:2px 5px;border-radius:4px;background:#ffffffed;color:#202124;font-size:12px;overflow-wrap:anywhere}.analysis-definition{display:grid;grid-template-columns:minmax(120px,1fr) minmax(0,2fr);gap:8px 16px;margin:0}.analysis-definition dt{color:var(--muted);font-size:13px}.analysis-definition dd{margin:0;overflow-wrap:anywhere}.analysis-screen .analysis-table{min-width:850px}.analysis-detail{border-left:3px solid var(--accent)}.analysis-metric{font-size:26px;font-weight:650;letter-spacing:-.5px}.analysis-group{background:#f1f3f6;font-weight:600}.analysis-screen details>summary{cursor:pointer;font-weight:600;padding:4px 0}.analysis-screen details[open]>summary{margin-bottom:16px}.analysis-evidence{display:flex;flex-direction:column;gap:16px}.analysis-legend{display:flex;gap:12px;flex-wrap:wrap;font-size:13px}.analysis-key{display:inline-flex;align-items:center;gap:6px}.analysis-key i{width:14px;height:14px;border-radius:4px}.analysis-screen .selected-label{color:var(--accent);font-size:13px}.analysis-screen .card-header{flex-wrap:wrap}.analysis-screen .alert p:last-child{margin-bottom:0}@media(max-width:1100px){.analysis-visuals{grid-template-columns:1fr}.analysis-regions{grid-template-columns:repeat(6,minmax(0,1fr));min-height:100px}}@media(max-width:600px){.analysis-regions{grid-template-columns:repeat(3,minmax(0,1fr))}.analysis-definition{grid-template-columns:1fr;gap:4px}.analysis-definition dd{margin-bottom:10px}.analysis-screen .analysis-metric{font-size:23px}}`);
  function render(ctx) {
    const host=h('div',{class:'analysis-screen'});
    const loading=h('p',{class:'loading-label',role:'status'},'Сравниваем результат с планом…');
    const loaded=App.load(()=>build(ctx));
    host.append(loading,loaded);
    const observer=new MutationObserver(()=>{if(!loaded.hasAttribute('aria-busy')){loading.remove();observer.disconnect();}});
    observer.observe(loaded,{attributes:true,attributeFilter:['aria-busy']});
    return host;
  }
  function build(ctx) {
    let pair=DB.get(entities.pair,ctx.params.id);
    if(!pair){const o=DB.get(entities.observation,ctx.params.id);if(o)pair=DB.get(entities.pair,o.pairId);}
    const empty=()=>h('section',{class:'empty-state'},h('h2',{},'Для отчёта нужны принятые наблюдения'),h('p',{},'Примите проверенную пару файла LightBurn и фотографии со стенда.'),link('Добавить наблюдение','/ingest'));
    if(ctx.proto.empty || !pair)return empty();
    const observations=all(entities.observation,{pairId:pair.id});
    if(!observations.length)return empty();
    const plan=pair.planId?DB.get(entities.plan,pair.planId):null;
    const profile=DB.get(entities.profile,pair.profileId);
    const stand=pair.standId?DB.get(entities.stand,pair.standId):null;
    const model=all(entities.model,{profileId:pair.profileId}).slice(-1)[0];
    const knowledge=all(entities.knowledge,{profileId:pair.profileId});
    const tonal=plan?.mode==='Тональная фотогравировка';
    const along=plan?.mode==='Фотогравировка по цветовому пути';
    const knownMode=tonal||along||plan?.mode==='Цветная гравировка';
    let reports=all(entities.report,{pairId:pair.id});
    let saved={};const storageKey='titanium.analysis.view.'+pair.id;
    try{saved=JSON.parse(localStorage.getItem(storageKey)||'{}');}catch(_){}
    let selected=observations.some(o=>o.id===(ctx.query.get('observation')||saved.selected))?(ctx.query.get('observation')||saved.selected):observations[0].id;
    let group=['parameters','batch','focus'].includes(saved.group)?saved.group:'parameters';
    let metric=saved.metric===true, busy=false;
    const root=h('div',{class:'analysis-screen'}), body=h('div',{class:'stack'}), operation=h('div',{});
    function persist(){try{localStorage.setItem(storageKey,JSON.stringify({selected,group,metric}));}catch(_){}}
    const reportFor=o=>reports.find(r=>r.observationId===o.id)||{measuredLab:o.lab,plannedLab:null,deltaE:null,limitations:[],reproducibility:{},standRepeatability:{}};
    const layerFor=o=>plan?.layers?.find(l=>l.regionId===o.regionId||l.id===o.layerId);
    function select(id){selected=id;persist();draw();}
    function evidence(o) {
      const source=DB.get(entities.pair,o.pairId),material=o.materialId?DB.get(entities.material,o.materialId):null;
      const content=h('div',{class:'analysis-evidence'},h('div',{class:'alert'},'Измеренный цвет сохранён неизменяемым. Производные расчёты не изменяют наблюдение.'),h('div',{class:'row'},swatch(o.lab),h('strong',{},lab(o.lab))),definition([['Наблюдение',o.id],['Область',o.regionId],['Файл LightBurn',source?.lightburnFile?.name||'Неизвестно'],['Фотография RAW',source?.photo?.name||'Неизвестно'],['Изделие',unknown(o.pieceId)],['Версия профиля',profile?`${profile.name} · версия ${profile.version}`:'Неизвестно'],['Выравнивание',unknown(o.alignmentMethod)],['Материал',material?.name||'Неизвестно'],['Партия или лист',unknown(o.batch)],['Фокус',unknown(o.focus)],['Дата гравировки',unknown(o.engravedAt)],['Примечание',unknown(o.note)]]),h('h3',{},'Полный вектор параметров'),vector(o.parameters),h('h3',{},'Качество и допуски'),definition([['Эталон',source?.reference?.detected&&source?.reference?.corrected?'Обнаружен; коррекция выполнена':'Нет подтверждённой коррекции'],['Измерение','Внутри маски области; края исключены'],['Допуск к модели',(o.modelEligibility?.allowed?'Допущено. ':'Не допущено. ')+(o.modelEligibility?.reason||'Причина не определена')],['Допуск к независимым повторам',(o.repeatEligibility?.allowed?'Допущено. ':'Не допущено. ')+(o.repeatEligibility?.reason||'Допуск к независимым повторам ещё не определён')]]));
      content.append(discrepancies(source));
      App.modal({title:'Наблюдение '+o.id,body:content,actions:[{label:'Закрыть',onClick:api=>api.close()}]});
    }
    function discrepancies(source) {
      const entries=source?.discrepancies||[];
      const section=h('section',{},h('h3',{},'История расхождений платы'));
      if(!entries.length){section.append(h('p',{class:'muted'},'Расхождений с определением платы не зарегистрировано.'));return section;}
      const labels={power:'Мощность',frequency:'Частота',speed:'Скорость'};
      section.append(h('div',{class:'table-wrap'},h('table',{class:'table'},h('thead',{},h('tr',{},['Ячейка','Поле','Определение','Файл'].map(t=>h('th',{scope:'col'},t)))),h('tbody',{},entries.map(d=>h('tr',{},h('td',{},d.cellId),h('td',{},labels[d.field]||d.field),h('td',{},n(d.defined)),h('td',{},n(d.fromFile))))))));
      section.append(h('p',{class:'alert'},source.fileConfirmation?source.fileConfirmation.text+' · '+date(source.fileConfirmation.at)+' · '+source.fileConfirmation.fileName:'Использованный файл не подтверждён.'));
      return section;
    }
    async function recalculate(){
      if(busy)return;busy=true;operation.replaceChildren(h('p',{role:'status',class:'loading-label'},'Сравниваем результат с планом…'));draw();
      try{await DB.run('buildReport',pair.id);reports=all(entities.report,{pairId:pair.id});operation.replaceChildren(h('p',{role:'status',class:'alert alert-success'},'Отчёт пересчитан. Исходные измерения сохранены.'));}
      catch(_){operation.replaceChildren(h('div',{class:'alert alert-danger',role:'alert'},h('p',{},'Не удалось построить отчёт'),button('Повторить расчёт',recalculate)));}
      finally{busy=false;draw();}
    }
    async function repeatPhoto(){
      if(busy)return;busy=true;draw();
      try{const next=await DB.run('repeatPhoto',pair.id);App.navigate('/ingest?pair='+encodeURIComponent(next.id)+'&pairId='+encodeURIComponent(next.id));}
      catch(e){App.toast(e.message||'Не удалось подготовить повторную фотографию','error');}
      finally{busy=false;if(root.isConnected)draw();}
    }
    function visual(title,kind) {
      const panel=h('section',{class:'analysis-visual'},h('h3',{},title));
      const tiles=h('div',{class:'analysis-regions'});
      observations.forEach((o,i)=>{
        const r=reportFor(o),l=layerFor(o);
        let value=kind==='measured'?o.lab:kind==='source'?(plan?.sourceColors?.find(c=>l?.sourceColorIds?.includes(c.id))?.lab||null):r.plannedLab;
        let background=color(value),label=String(i+1);
        if(kind==='deviation'){
          const deviation=tonal?(r.plannedBrightness==null?null:r.measuredBrightness-r.plannedBrightness):r.deltaE;
          background=deviation==null?'#e7e9ee':Math.abs(deviation)<=2?'#dcefe6':Math.abs(deviation)<=4?'#ffe5ae':'#f6c5cb';
          label=deviation==null?'Нет данных':(tonal?'ΔL ':'ΔE ')+n(deviation);
        }
        tiles.append(h('button',{type:'button',class:'analysis-region',style:{background},'aria-pressed':String(selected===o.id),'aria-label':title+', область '+(i+1)+', '+o.regionId+', '+(kind==='deviation'?label:lab(value)),onClick:()=>select(o.id)},h('span',{},'Область '+(i+1)+' · '+label)));
      });
      panel.append(tiles,h('p',{class:'field-help',style:{marginTop:'12px',marginBottom:'0'}},kind==='source'?(plan?.image?'Исходное изображение: '+plan.image.name+'. Демонстрационная схема областей; пиксели файла не хранятся.':'Нет исходных данных: исходное изображение отсутствует.'):'Демонстрационная схема областей. Выберите область для просмотра измерения.'));
      return panel;
    }
    function draw(){
      body.replaceChildren();
      const top=h('section',{class:'card'},h('div',{class:'card-header'},h('div',{},h('h2',{},pair.name||pair.id),h('p',{class:'muted',style:{margin:'6px 0 0'}},pair.id+' · '+(plan?.mode||'Режим неизвестен'))),h('span',{class:'badge badge-success'},'Наблюдения приняты')),definition([['Исходный план',plan?link(plan.name||plan.id,path('/plans',plan.id)):'Нет исходных данных'],['Версия профиля',profile?`${profile.name} · версия ${profile.version}`:'Неизвестно'],['Файл LightBurn',pair.lightburnFile?.name||'Неизвестно'],['Фотография',pair.photo?.name||'Неизвестно'],['Эталон',pair.reference?.detected&&pair.reference?.corrected?'Обнаружен; цветовая коррекция выполнена':'Нет подтверждённых данных'],['Выравнивание',pair.alignment?.method||'Неизвестно'],['Установка съёмки',stand?.name||'Неизвестно']]));
      body.append(top);
      if(!knownMode)body.append(h('p',{class:'alert'},'Нет исходных данных для сравнения режима. Доступны измерения и сравнение повторов.'));
      const comparison=h('section',{class:'card'},h('div',{class:'card-header'},h('h2',{},'Сопоставление областей')));
      if(knownMode){const label=tonal?'Яркость и контраст':along?'ΔE вдоль пути':'Цветовые отклонения';comparison.append(h('div',{class:'toolbar'},h('button',{type:'button',class:'btn'+(metric?' btn-primary':''),'aria-pressed':String(metric),onClick:()=>{metric=!metric;persist();draw();}},label),h('span',{class:'muted text-sm'},metric?'Показана карта отклонений':'Показаны исходные данные и результат')));}
      comparison.append(h('div',{class:'analysis-visuals',style:{marginTop:'16px'}},visual('Исходное изображение','source'),visual('Прогноз плана','planned'),visual(metric?'Карта отклонений':'Скорректированная фотография',metric?'deviation':'measured')));
      if(metric)comparison.append(h('div',{class:'analysis-legend',style:{marginTop:'16px'}},[['#dcefe6','0–2'],['#ffe5ae','Больше 2–4'],['#f6c5cb','Больше 4'],['#e7e9ee','Нет исходных данных']].map(([c,t])=>h('span',{class:'analysis-key'},h('i',{style:{background:c},'aria-hidden':'true'}),t)),h('span',{},tonal?'Шкала |ΔL|, единицы Lab':'Шкала ΔE; демонстрационные интервалы')));
      if(along){const transfer=plan.transferId?DB.get('Передаточная функция',plan.transferId):null;comparison.append(h('h3',{style:{marginTop:'20px'}},'Выбранная траектория'),h('div',{class:'row'},(transfer?.path||[]).length?transfer.path.map((id,i)=>{const k=DB.get(entities.knowledge,id);return h('div',{class:'row'},h('span',{},String(i+1)),swatch(k?.lab),link(k?lab(k.lab):id,path('/knowledge',id)));}):h('p',{class:'muted'},'Нет исходных данных о выбранной траектории.')));}
      body.append(comparison);
      const selector=h('select',{class:'select',value:group,onChange:e=>{group=e.target.value;persist();draw();}},[['parameters','По параметрам'],['batch','По партии или листу'],['focus','По фокусу']].map(([v,t])=>h('option',{value:v,selected:group===v},t)));
      const tableCard=h('section',{class:'card'},h('div',{class:'card-header'},h('h2',{},'Измерения по областям'),h('label',{class:'row'},h('span',{class:'field-label'},'Группировать'),selector)));
      const headings=['Область','Параметры','Плановый Lab','Измеренный Lab',tonal?'Яркость и контраст':'ΔE','Уверенность плана','Ожидаемая ошибка','Стабильность'];
      const tbody=h('tbody',{}),groups=DB.groupObservations(pair.id,group);
      Object.entries(groups).forEach(([key,rows])=>{
        const first=rows[0];
        const title=group==='parameters'?`Мощность ${n(first.parameters.power)} % · частота ${n(first.parameters.frequency)} кГц · скорость ${n(first.parameters.speed)} мм/с`:group==='focus'?(key==='Неизвестно'?key:'Фокус: '+key):'Партия или лист: '+key;
        tbody.append(h('tr',{class:'analysis-group'},h('td',{colspan:8},title)));
        rows.forEach(o=>{const r=reportFor(o),l=layerFor(o);tbody.append(h('tr',{class:selected===o.id?'selected':''},h('td',{},h('button',{type:'button',class:'btn btn-ghost btn-small','aria-pressed':String(selected===o.id),onClick:()=>select(o.id)},o.regionId)),h('td',{},`${n(o.parameters.power)} % · ${n(o.parameters.frequency)} кГц · ${n(o.parameters.speed)} мм/с`),h('td',{},lab(r.plannedLab)),h('td',{},h('div',{class:'row'},swatch(o.lab),lab(o.lab))),h('td',{},tonal?[h('div',{},'План: '+n(r.plannedBrightness)),h('div',{},'Измерено: '+n(r.measuredBrightness)),h('div',{},'ΔL: '+n(r.plannedBrightness==null?null:r.measuredBrightness-r.plannedBrightness)),h('div',{},'Контраст: '+n(r.contrast?.planned)+' → '+n(r.contrast?.measured))]:n(r.deltaE)),h('td',{},l?.confidence==null?'Нет исходных данных':n(l.confidence)+' / 1'),h('td',{},l?.expectedDeltaE==null?'Нет исходных данных':'ΔE '+n(l.expectedDeltaE)),h('td',{},l?.stability?.assessed?'Разброс: '+n(l.stability.variance):'Не оценена')));});
      });
      tableCard.append(h('div',{class:'table-wrap'},h('table',{class:'table analysis-table'},h('caption',{class:'sr-only'},'Измерения, прогноз и отклонения по областям'),h('thead',{},h('tr',{},headings.map(t=>h('th',{scope:'col'},t)))),tbody)));
      body.append(tableCard);
      const o=observations.find(x=>x.id===selected),r=reportFor(o),l=layerFor(o),k=knowledge.find(x=>x.observationIds?.includes(o.id));
      const detail=h('section',{class:'card analysis-detail'},h('div',{class:'card-header'},h('h2',{},'Область '+o.regionId),button('Наблюдение',()=>evidence(o))),h('div',{class:'grid'},h('div',{},h('div',{class:'row'},swatch(o.lab),h('strong',{},lab(o.lab))),vector(o.parameters)),h('div',{},definition([['Плановый цвет',lab(r.plannedLab)],['Отклонение',tonal?'ΔL '+n(r.plannedBrightness==null?null:r.measuredBrightness-r.plannedBrightness):'ΔE '+n(r.deltaE)],['Независимые повторы',o.repeatEligibility?.allowed?n(r.reproducibility?.independentRepeats):'Не определено'],['Допуск к модели',(o.modelEligibility?.allowed?'Допущено. ':'Не допущено. ')+(o.modelEligibility?.reason||'Нет данных')],['Допуск к повторам',(o.repeatEligibility?.allowed?'Допущено. ':'Не допущено. ')+(o.repeatEligibility?.reason||'Допуск к независимым повторам ещё не определён')]]))));
      if(k)detail.append(h('p',{style:{marginTop:'16px',marginBottom:0}},link('Запись знания',path('/knowledge',k.id))));
      if(!o.batch||o.focus==null)detail.append(h('p',{class:'alert alert-warning',style:{marginTop:'16px',marginBottom:0}},'Контекст неизвестен: связать отклонение с партией или фокусом нельзя'));
      if(!l?.stability?.assessed)detail.append(h('p',{class:'field-help',style:{marginTop:'12px',marginBottom:0}},'Стабильность не оценена: недостаточно данных независимых гравировок.'));
      body.append(detail);
      const summary=h('section',{class:'card'},h('h2',{},'Воспроизводимость и повторяемость стенда'));
      const eligible=observations.filter(x=>x.repeatEligibility?.allowed);
      const repeats=eligible.length?Math.max(...eligible.map(x=>reportFor(x).reproducibility?.independentRepeats||0)):null;
      const standReports=reports.filter(x=>x.standRepeatability?.assessed);
      summary.append(h('div',{class:'grid'},h('div',{},h('h3',{},'Независимые гравировки'),h('p',{class:'analysis-metric'},repeats==null?'Не определено':n(repeats)),h('p',{class:'muted'},'Допустимые независимые повторы для представленных параметров; показано наибольшее число.'),h('p',{class:'alert'},repeats==null||repeats<2?'Недостаточно независимых повторов для оценки воспроизводимости':'Разброс повторов: '+n(r.reproducibility?.variance??k?.stability?.variance)+' · демонстрационная оценка')),h('div',{},h('h3',{},'Повторяемость фотостенда'),h('p',{class:'analysis-metric'},standReports.length?'ΔE '+n(standReports.reduce((s,x)=>s+(x.standRepeatability.deltaE||0),0)/standReports.length):'Не оценена'),h('p',{class:'muted'},standReports.length?'Среднее отклонение повторных фотографий того же изделия.':'Нет повторной фотографии того же изделия.'),h('p',{class:'alert'},'Одна фотография не доказывает стабильность. Повторная фотография изделия не считается независимой гравировкой.'))));
      const unstable=knowledge.filter(x=>x.questionable&&x.observationIds?.some(id=>observations.some(v=>v.id===id)));
      summary.append(h('h3',{},'Нестабильные параметры'),unstable.length?h('div',{class:'stack'},unstable.map(x=>h('div',{class:'alert alert-warning'},link('Запись знания '+x.id,path('/knowledge',x.id)),h('p',{style:{margin:'8px 0 0'}},`${n(x.parameters.power)} % · ${n(x.parameters.frequency)} кГц · ${n(x.parameters.speed)} мм/с · Под вопросом`)))):h('p',{class:'muted'},'Среди связанных записей нет параметров с флагом «Под вопросом».'));
      body.append(summary);
      const changes=h('section',{class:'card'},h('h2',{},'Изменения производных знаний'));
      changes.append(h('p',{class:'alert '+(model?.observationIds?.length?'alert-success':'')},model?.observationIds?.length?'Модель обновлена по принятым измерениям · версия '+model.version:'Нет подтверждённого состояния обновления модели.'));
      if(!model?.rules?.agreed)changes.append(h('p',{class:'alert alert-warning'},'Автоматическая валидация ожидает согласования критериев',h('br'),link('Правила оценки','/profiles?tab=rules')));
      else changes.append(h('p',{class:'field-help'},'Используются условно согласованные демонстрационные критерии.'));
      const caused=knowledge.filter(x=>x.questionable&&x.doubtObservationIds?.some(id=>observations.some(v=>v.id===id)));
      if(!caused.length)changes.append(h('p',{class:'muted'},'Нет записей, для которых эти наблюдения зарегистрированы как основания флага «Под вопросом».'));
      caused.forEach(x=>changes.append(h('div',{class:'alert alert-warning'},h('div',{class:'row'},link('Запись знания '+x.id,path('/knowledge',x.id)),h('span',{class:'badge badge-warning'},'Под вопросом'),h('span',{},'Стадия: '+x.stage)),h('p',{style:{margin:'10px 0'}},x.doubtReason||'Требуется проверка оснований'),h('div',{class:'row'},x.doubtObservationIds.map(id=>{const basis=DB.get(entities.observation,id);return basis?link('Наблюдение '+id,path('/analysis',basis.pairId)+'?observation='+encodeURIComponent(id)):h('span',{},id);})),h('p',{class:'field-help',style:{margin:'10px 0 0'}},'Флаг не понижает стадию автоматически. Производственное решение требует явного ручного действия.'))));
      const history=h('details',{},h('summary',{},'Расхождения и подтверждение использованного файла'),discrepancies(pair));changes.append(history);
      body.append(changes);
      const actions=h('div',{class:'toolbar'},link('К экспериментам','/experiments'),link('Карта цветов','/colors?profile='+encodeURIComponent(pair.profileId)),link('Следующий эксперимент','/designer?profile='+encodeURIComponent(pair.profileId)),h('span',{class:'spacer'}));
      const repeat=button('Повторная фотография этого изделия',repeatPhoto);repeat.disabled=busy||pair.status!=='Принята';
      const recalc=button('Повторить расчёт',recalculate);recalc.disabled=busy;
      actions.append(repeat,recalc);body.append(actions);
      if(pair.status!=='Принята')body.append(h('p',{class:'field-help'},'Повторная фотография доступна после принятия пары.'));
    }
    root.append(operation,body);draw();return root;
  }
  App.register({id:'analysis',route:'/analysis/:id',title:'Анализ после гравировки',render});
})();
