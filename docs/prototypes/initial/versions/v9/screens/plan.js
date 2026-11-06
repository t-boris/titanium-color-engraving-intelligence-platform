(function () {
  'use strict';
  const h = App.h;
  const E = {plan:'План гравировки',profile:'Профиль лазера',board:'Калибровочная плата',pair:'Пара входных файлов',transfer:'Передаточная функция',knowledge:'Запись знания',model:'Модель цветового пространства'};
  const enc = encodeURIComponent;
  const number = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ru-RU',{maximumFractionDigits:3}) : 'Не задано';
  const lab = value => value ? 'Lab ' + [value.L,value.a,value.b].map(number).join(' · ') : 'Прогноз пока недоступен';
  const link = (label,route) => h('a',{href:'#'+route},label);
  const button = (label,handler,kind,disabled) => h('button',{type:'button',class:'btn '+(kind||''),disabled:!!disabled,onClick:handler},label);
  const list = (entity,filter) => DB.list(entity,{filter,pageSize:10000}).items;
  function svg(tag,attrs,children) {
    const node = document.createElementNS('http://www.w3.org/2000/svg',tag);
    Object.entries(attrs||{}).forEach(([key,value])=>node.setAttribute(key,String(value)));
    (children||[]).forEach(child=>node.append(child));
    return node;
  }
  function color(value) {
    if(!value) return '#edf0f4';
    const fy=(value.L+16)/116, fx=fy+value.a/500, fz=fy-value.b/200;
    const inv=t=>t*t*t>0.008856?t*t*t:(t-16/116)/7.787;
    const x=0.95047*inv(fx),y=inv(fy),z=1.08883*inv(fz);
    const gamma=t=>Math.round(255*Math.max(0,Math.min(1,t<=0.0031308?12.92*t:1.055*Math.pow(t,1/2.4)-0.055)));
    return 'rgb('+[3.2406*x-1.5372*y-0.4986*z,-0.9689*x+1.8758*y+0.0415*z,0.0557*x-0.204*y+1.057*z].map(gamma).join(',')+')';
  }
  function facts(rows) {
    return h('dl',{class:'plan-facts'},rows.map(([label,value])=>[h('dt',{},label),h('dd',{},value==null||value===''?'Не задано':value)]));
  }
  function params(value) {
    value=value||{};
    return facts([['Мощность',number(value.power)+' %'],['Частота',number(value.frequency)+' кГц'],['Скорость',number(value.speed)+' мм/с'],['Длительность импульса',number(value.pulseDuration)+' нс'],['Интервал линий',number(value.lineInterval)+' мм'],['Проходы',number(value.passes)]]);
  }
  function shape(value) {
    if(!value) return 'Геометрия не задана';
    return Object.entries(value).map(([key,v])=>({x:'X',y:'Y',width:'Ширина',height:'Высота',row:'Строка',column:'Столбец',outsideImage:'Вне изображения',outsideGrid:'Вне сетки',enabled:'Включены',machineId:'Машинный идентификатор',size:'Размер',cellWidth:'Ширина ячейки',cellHeight:'Высота ячейки',gap:'Промежуток',columns:'Столбцы',rows:'Строки'}[key]||key)+': '+(typeof v==='boolean'?(v?'Да':'Нет'):typeof v==='number'?number(v):typeof v==='object'?JSON.stringify(v):v)).join(' · ');
  }
  App.addStyles(`
    .plan-screen .plan-facts{display:grid;grid-template-columns:minmax(120px,1fr) minmax(0,1.5fr);gap:8px 16px;margin:0}.plan-screen dt{color:var(--muted);font-size:13px}.plan-screen dd{margin:0;overflow-wrap:anywhere}.plan-screen .plan-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}.plan-screen .plan-summary small{display:block;color:var(--muted);margin-bottom:5px}.plan-screen .plan-canvas{width:100%;height:340px;border:1px solid var(--line);border-radius:12px;background:#fafbfc;display:block}.plan-screen .plan-canvas [role=button]{cursor:pointer}.plan-screen .plan-canvas [role=button]:focus{outline:none;stroke:var(--accent);stroke-width:2}.plan-screen .plan-layer-button{display:flex;gap:10px;align-items:center;border:0;background:none;padding:0;text-align:left;color:var(--accent);font:inherit;cursor:pointer}.plan-screen .plan-layer-button .swatch{min-width:28px;width:28px;height:28px;border-radius:7px}.plan-screen .plan-scroll{max-height:560px;overflow:auto}.plan-screen .plan-export{border-color:#cbdff8}.plan-screen .plan-detail{scroll-margin-top:100px}.plan-screen .plan-detail h3{margin-bottom:12px}.plan-screen .plan-caption{font-size:13px;color:var(--muted);margin:12px 0 0}.plan-screen .plan-history-row{padding:12px 0;border-bottom:1px solid var(--line)}.plan-screen .plan-history-row:last-child{border-bottom:0}.plan-screen .plan-metric{font-size:22px;font-weight:600}.plan-screen .plan-image-name{overflow-wrap:anywhere}.plan-screen .plan-actions{justify-content:space-between}.plan-screen .plan-table td{min-width:105px}.plan-screen .plan-table td:first-child{min-width:170px}@media(max-width:600px){.plan-screen .plan-summary{grid-template-columns:1fr}.plan-screen .plan-canvas{height:270px}.plan-screen .plan-facts{grid-template-columns:1fr;gap:3px}.plan-screen dd{margin-bottom:10px}}
  `);
  function build(ctx) {
    const host=h('div',{class:'plan-screen stack'});
    let plan=ctx.proto.empty?null:DB.get(E.plan,ctx.params.id);
    if(!plan) return h('section',{class:'empty-state'},h('h2',{},'План гравировки не найден'),link('К экспериментам','/experiments'));
    let selected='';
    try {selected=localStorage.getItem('titanium.plan.selection.'+plan.id)||'';}catch(_){}
    if(!(plan.layers||[]).some(layer=>layer.id===selected)) selected=plan.layers?.[0]?.id||'';
    let busy=false,exportError=false,resultError='',lastResultAction=null;
    function choose(id,focus) {
      selected=id;
      try{localStorage.setItem('titanium.plan.selection.'+plan.id,id);}catch(_){}
      draw();
      if(focus) host.querySelector('.plan-detail')?.focus({preventScroll:true});
    }
    function ready() {
      if(!['Готов к экспорту','Экспортирован'].includes(plan.status)||!plan.layers?.length) return false;
      if(plan.matches?.some(c=>c.status==='Недостижим')) return false;
      if(['Калибровочная плата','Восстановленный из файла'].includes(plan.mode)) return true;
      return plan.layers.every(l=>l.lab&&Number.isFinite(l.confidence)&&Number.isFinite(l.expectedDeltaE)&&l.stability?.assessed===true);
    }
    async function exportFile() {
      if(busy) return;
      busy=true;exportError=false;draw();
      try {await DB.run('exportPlan',plan.id);plan=DB.get(E.plan,plan.id);App.toast('Файл подготовлен','success');}
      catch(error){exportError=true;App.toast('Не удалось экспортировать план','error');}
      finally{busy=false;draw();}
    }
    function download() {
      const file=plan.exportFile;
      if(!file?.content) return;
      const url=URL.createObjectURL(new Blob([file.content],{type:file.mime||'application/json'}));
      const anchor=h('a',{href:url,download:file.name});document.body.append(anchor);anchor.click();anchor.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
      App.toast('Демонстрационный файл скачан','success');
    }
    async function result() {
      if(busy) return;
      busy=true;resultError='';lastResultAction=result;draw();
      try {const pair=await DB.run('addPlanResult',plan.id);App.navigate('/ingest?pair='+enc(pair.id)+'&plan='+enc(plan.id));}
      catch(_){resultError='Не удалось добавить результат гравировки';}
      finally{busy=false;draw();}
    }
    async function markers(enabled) {
      if(busy) return;
      busy=true;resultError='';lastResultAction=()=>markers(enabled);draw();
      try{await DB.run('setPlanMarkers',plan.id,enabled);plan=DB.get(E.plan,plan.id);App.toast('Регистрационные маркеры сохранены','success');}
      catch(_){resultError='Не удалось сохранить регистрационные маркеры';}
      finally{busy=false;draw();}
    }
    function geometry() {
      const layers=plan.layers||[];
      const normalized=layers.some(l=>l.geometry?.width<=1&&l.brightnessRange);
      const scale=normalized?100:1;
      const geometries=layers.map(l=>({l,g:l.geometry||null})).filter(x=>x.g&&['x','y','width','height'].every(k=>Number.isFinite(x.g[k])));
      if(!geometries.length) return h('div',{class:'empty-state'},h('p',{},'Геометрия областей не задана'),h('p',{},'Параметры и прогнозы доступны в таблице слоёв.'));
      const minX=Math.min(0,...geometries.map(x=>x.g.x*scale));
      const minY=Math.min(0,...geometries.map(x=>x.g.y*scale));
      const maxX=Math.max(...geometries.map(x=>(x.g.x+x.g.width)*scale));
      const maxY=Math.max(...geometries.map(x=>(x.g.y+x.g.height)*scale));
      const pad=Math.max(maxX-minX,maxY-minY)*0.12+2;
      const canvas=svg('svg',{viewBox:[minX-pad,minY-pad,maxX-minX+pad*2,maxY-minY+pad*2].join(' '),class:'plan-canvas',role:'group','aria-label':'Геометрия плана. Выберите слой или полосу'});
      geometries.forEach(({l,g},i)=>{
        const group=svg('g',{role:'button',tabindex:'0','aria-label':(l.brightnessRange?'Полоса ':'Слой ')+(i+1)+', '+l.id,'aria-pressed':String(l.id===selected)});
        const rect=svg('rect',{x:g.x*scale,y:g.y*scale,width:g.width*scale,height:g.height*scale,rx:normalized?0:0.4,fill:color(l.lab),stroke:l.id===selected?'#0066d6':'#b6bdc7','stroke-width':l.id===selected?Math.max(0.5,pad/12):Math.max(0.15,pad/40)});
        rect.append(svg('title',{},[document.createTextNode(l.id+' · '+lab(l.lab))]));group.append(rect);
        group.addEventListener('click',()=>choose(l.id,true));
        group.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(l.id,true);}});
        canvas.append(group);
      });
      if(plan.markers) {
        const size=Math.min(pad/3,Number(plan.markerGeometry?.size)||2);
        [[minX-pad/2,minY-pad/2],[maxX+pad/2,minY-pad/2],[maxX+pad/2,maxY+pad/2],[minX-pad/2,maxY+pad/2]].forEach(([x,y])=>canvas.append(svg('path',{d:`M ${x-size} ${y} H ${x+size} M ${x} ${y-size} V ${y+size}`,stroke:'#202124','stroke-width':Math.max(0.25,size/4),fill:'none','aria-hidden':'true'})));
      }
      return canvas;
    }
    function draw() {
      const profile=DB.get(E.profile,plan.profileId),model=plan.modelId?DB.get(E.model,plan.modelId):null;
      const board=plan.boardId?DB.get(E.board,plan.boardId):list(E.board,{planId:plan.id})[0];
      const transfer=plan.transferId?DB.get(E.transfer,plan.transferId):null;
      const calibration=plan.mode==='Калибровочная плата';
      const photo=plan.mode==='Тональная фотогравировка'||plan.mode==='Фотогравировка по цветовому пути';
      const imported=plan.mode==='Восстановленный из файла';
      const layer=(plan.layers||[]).find(l=>l.id===selected);
      host.replaceChildren();
      host.append(h('div',{class:'row plan-actions'},link('← К экспериментам','/experiments'),h('span',{class:'badge '+(plan.status==='Черновик'?'badge-warning':'badge-info')},plan.status),button('Удалить план',()=>App.removeRecord(E.plan,plan,()=>App.navigate('/experiments')),'btn-danger',busy)));
      host.append(h('section',{class:'card'},h('h2',{},plan.name||plan.id),h('div',{class:'plan-summary'},h('div',{},h('small',{},'Идентификатор плана'),h('strong',{},plan.id)),h('div',{},h('small',{},'Режим'),h('strong',{},plan.mode)),h('div',{},h('small',{},'Слои'),h('strong',{class:'plan-metric'},(plan.layers||[]).length))),h('hr',{class:'divider'}),facts([['Версия профиля',profile?profile.name+' · версия '+profile.version:'Профиль не найден'],['Версия модели',model?.version||'Не задано'],['Исходное изображение',plan.image?.name||'Нет исходного изображения'],['Определение платы',board?board.experimentId+' · '+shape(board.geometry):calibration?'Определение платы не найдено':'Не применяется']])));
      if(plan.status==='Черновик') host.append(h('div',{class:'alert alert-warning',role:'status'},'План требует завершения преобразования'));
      if(!ready()&&plan.status!=='Черновик') host.append(h('div',{class:'alert alert-warning'},'Экспорт недоступен: нужны слои с допустимыми параметрами и полными показателями прогноза.'));
      const usedQuestionable=(plan.layers||[]).filter(l=>l.questionable);
      const allowed=plan.allowedQuestionableIds||[];
      if(usedQuestionable.length||allowed.length) host.append(h('section',{class:'alert alert-warning'},h('h3',{},plan.mode==='Тональная фотогравировка'?'Используются производственные параметры под вопросом':'Параметры под вопросом включены в этот план'),h('p',{},'Создание и экспорт плана не изменяют стадию и флаг знания.'),h('div',{class:'row'},[...new Set([...usedQuestionable.map(l=>l.knowledgeId),...allowed])].filter(Boolean).map(id=>link('Наблюдения · '+id,'/knowledge/'+enc(id))))));
      else host.append(h('p',{class:'muted text-sm'},'Разрешения использовать параметры под вопросом: отсутствуют.'));
      const markerCheck=h('input',{type:'checkbox',checked:!!plan.markers,disabled:calibration||busy,onChange:e=>markers(e.target.checked)});
      const geometryCard=h('section',{class:'card'},h('div',{class:'card-header'},h('h2',{},calibration?'Сетка калибровочной платы':'Геометрия гравировки'),!calibration&&!imported?link('Редактировать преобразование',(photo?'/photo':'/artwork')+'?plan='+enc(plan.id)):null),geometry(),h('p',{class:'plan-caption'},'Геометрия показана по данным плана. Цветовые образцы на экране служат демонстрацией.'),h('hr',{class:'divider'}),h('label',{class:'check'},markerCheck,h('span',{},'Регистрационные маркеры')),h('p',{class:'plan-caption'},calibration?'Маркеры и машинный идентификатор обязательны для калибровочной платы.':'Маркеры и машинный идентификатор размещаются вне изображения.'),facts([['Геометрия маркеров',plan.markers?shape(plan.markerGeometry||board?.markers):'Выключены'],['Машинный идентификатор',plan.markers?(plan.markerGeometry?.machineId||board?.markers?.machineId||'Не задано'):'Выключен']]),board?facts([['Мощность по столбцам',board.powerValues.map(number).join(' · ')+' %'],['Частота по строкам',board.frequencyValues.map(number).join(' · ')+' кГц'],['Скорость платы',number(board.speed)+' мм/с'],['Размеры сетки',shape(board.geometry)]]):null);
      const detail=h('section',{class:'card plan-detail',tabindex:'-1','aria-label':'Параметры выбранного слоя'});
      if(layer) detail.append(h('h2',{},(layer.brightnessRange?'Полоса':'Слой')+' · '+layer.id),params(layer.parameters),h('hr',{class:'divider'}),facts([['Геометрия',shape(layer.geometry)],['Маска или ячейки',(layer.sourceColorIds||[]).join(' · ')||layer.regionId||layer.id],['Прогнозный цвет',lab(layer.lab)],['Уверенность',Number.isFinite(layer.confidence)?number(layer.confidence)+' · шкала от 0 до 1':'Прогноз пока недоступен'],['Ожидаемая ошибка ΔE',Number.isFinite(layer.expectedDeltaE)?number(layer.expectedDeltaE):'Прогноз пока недоступен'],['Стабильность',layer.stability?.assessed?(layer.stability.label||'Оценена')+' · разброс '+number(layer.stability.variance):calibration?'Прогноз пока недоступен':'Не оценена'],['Стадия',layer.stage||'Не задано'],['Под вопросом',layer.questionable?'Да':'Нет'],...(layer.brightnessRange?[['Диапазон яркости',layer.brightnessRange.map(number).join(' — ')]]:[])]),layer.knowledgeId?link('Открыть знание','/knowledge/'+enc(layer.knowledgeId)):null);
      else detail.append(h('p',{class:'muted'},'В плане нет слоёв.'));
      host.append(h('div',{class:'split'},geometryCard,detail));
      if(photo) host.append(h('section',{class:'card'},h('h2',{},'Передаточная функция и полосы'),facts([['Число полос N',number(plan.bandCount)],['Передаточная функция',transfer?transfer.id+' · '+transfer.mode:'Не задано'],['Наблюдения-основания',transfer?.observationIds?.join(' · ')||'Нет исходных данных'],['Оценка функции',transfer?.assessment?.description||'Нет исходных данных'],['Ожидаемая яркость',transfer?.assessment?.brightness?.map(number).join(' — ')||'Нет исходных данных'],['Ожидаемый контраст',number(transfer?.assessment?.contrast)],['Цветовая траектория',transfer?.path?.length?transfer.path.join(' → '):'Не задана']]),transfer?.points?.length?h('details',{},h('summary',{},'Точки передаточной функции'),h('div',{class:'table-wrap'},h('table',{class:'table'},h('thead',{},h('tr',{},['Яркость','Прогнозный Lab','Запись знания'].map(v=>h('th',{scope:'col'},v)))),h('tbody',{},transfer.points.map(p=>h('tr',{},h('td',{},number(p.brightness)),h('td',{},lab(p.lab)),h('td',{},p.knowledgeId?link(p.knowledgeId,'/knowledge/'+enc(p.knowledgeId)):'Не задано'))))))):null));
      if(plan.mode==='Цветная гравировка') {
        const matches=plan.matches||[];
        host.append(h('section',{class:'card'},h('h2',{},'Выбранные цвета, замены и исключения'),facts([['Порог ΔE',number(plan.deltaThreshold)],['Нерешённые цвета',matches.filter(c=>c.status==='Недостижим').length],['Ручные замены',(plan.replacements||[]).length],['Исключения',(plan.exclusions||[]).length]]),matches.length?h('div',{class:'table-wrap'},h('table',{class:'table'},h('thead',{},h('tr',{},['Исходный цвет','Решение','Выбранный цвет','Фактическая ошибка ΔE'].map(v=>h('th',{scope:'col'},v)))),h('tbody',{},matches.map(c=>h('tr',{},h('td',{},c.id,h('div',{class:'muted text-sm'},lab(c.lab))),h('td',{},c.status),h('td',{},c.prediction?lab(c.prediction.lab):'Не задано'),h('td',{},number(c.prediction?.deltaE))))))):h('p',{class:'muted'},'Для этого демонстрационного плана подробные исходные соответствия не сохранены.'),...(plan.replacements||[]).map(r=>h('p',{},r.sourceColorId+' → ',link(r.knowledgeId,'/knowledge/'+enc(r.knowledgeId)))),(plan.exclusions||[]).length?h('p',{},'Исключённые цвета: '+plan.exclusions.join(' · ')):null));
      }
      host.append(h('section',{class:'card'},h('h2',{},photo?'Параметры каждой полосы':'Параметры каждого слоя'),h('p',{class:'muted text-sm'},'Выбор строки выделяет соответствующую геометрию. Константы берутся из сохранённой версии профиля.'),h('div',{class:'table-wrap plan-scroll'},h('table',{class:'table plan-table'},h('thead',{},h('tr',{},['Слой / полоса','Мощность, %','Частота, кГц','Скорость, мм/с','Прогнозный Lab','Уверенность','Ожидаемая ошибка ΔE','Стабильность','Стадия и флаг'].map(v=>h('th',{scope:'col'},v)))),h('tbody',{},(plan.layers||[]).map((l,i)=>h('tr',{class:l.id===selected?'selected':''},h('td',{},h('button',{type:'button',class:'plan-layer-button','aria-pressed':String(l.id===selected),onClick:()=>choose(l.id,true)},h('span',{class:'swatch',style:{background:color(l.lab)},'aria-hidden':'true'}),(i+1)+' · '+l.id),l.brightnessRange?h('div',{class:'text-sm muted'},l.brightnessRange.map(number).join(' — ')):null),h('td',{},number(l.parameters?.power)),h('td',{},number(l.parameters?.frequency)),h('td',{},number(l.parameters?.speed)),h('td',{},lab(l.lab)),h('td',{},Number.isFinite(l.confidence)?number(l.confidence):'Прогноз пока недоступен'),h('td',{},Number.isFinite(l.expectedDeltaE)?number(l.expectedDeltaE):'Прогноз пока недоступен'),h('td',{},l.stability?.assessed?'Разброс '+number(l.stability.variance):calibration?'Прогноз пока недоступен':'Не оценена'),h('td',{},l.stage||'Не задано',l.questionable?h('div',{class:'badge badge-warning'},'Под вопросом'):null))))))));
      const file=plan.exportFile;
      const exportCard=h('section',{class:'card plan-export stack','aria-busy':String(busy)},h('h2',{},'Экспорт в LightBurn'),h('p',{class:'muted'},'Физическая гравировка выполняется в LightBurn. Параметры результата снова читаются из фактически приложенного файла.'),h('div',{class:'alert alert-warning'},'Демонстрационный экспорт. Совместимость с вашей версией LightBurn требует проверки. Подготовленный артефакт содержит данные прототипа и не является рабочим файлом LightBurn.'),facts([['Имя файла',file?.name||'Файл ещё не подготовлен'],['Число слоёв',file?.layerCount??plan.layers?.length??0],['Состояние',busy?'Готовим файл LightBurn…':file?.content?'Файл подготовлен':file?'Требуется подготовить демонстрационный артефакт':'Ожидает экспорта']]));
      if(exportError) exportCard.append(h('div',{class:'alert alert-danger',role:'alert'},'Не удалось экспортировать план'));
      exportCard.append(h('div',{class:'row'},button(exportError?'Повторить экспорт':file?.content?'Подготовить файл повторно':'Экспортировать в LightBurn',exportFile,'btn-primary',busy||!ready()),file?.content?button('Скачать файл',download,'',busy):null));
      if(busy) exportCard.append(h('p',{role:'status',class:'muted'},'Выполняем действие…'));
      host.append(exportCard);
      const pairs=list(E.pair,{planId:plan.id});
      const related=new Map(pairs.map(p=>[p.id,p]));
      (plan.pairIds||[]).forEach(id=>{const p=DB.get(E.pair,id);if(p)related.set(id,p);});
      const results=h('section',{class:'card'},h('div',{class:'card-header'},h('h2',{},'Наблюдения и отчёты'),button('Добавить результат гравировки',result,'',busy)),h('p',{class:'muted text-sm'},'Прикрепите фотографию со стенда и фактически использованный файл LightBurn. Предложенный файл экспорта не принимается автоматически.'));
      if(!related.size) results.append(h('p',{class:'muted'},'Связанных результатов пока нет.'));
      related.forEach(pair=>results.append(h('div',{class:'plan-history-row row'},h('div',{class:'spacer'},h('strong',{},pair.name||pair.id),h('div',{class:'text-sm muted'},pair.id+' · '+pair.status),h('div',{class:'text-sm muted'},(pair.lightburnFile?.name||'Файл LightBurn не прикреплён')+' · '+(pair.photo?.name||'Фотография не прикреплена'))),link(pair.status==='Принята'?'Открыть анализ':'Проверить пару',pair.status==='Принята'?'/analysis/'+enc(pair.id):'/ingest?pair='+enc(pair.id)))));
      if(resultError) results.append(h('div',{class:'alert alert-danger',role:'alert'},h('p',{},resultError),button('Повторить',()=>lastResultAction&&lastResultAction(),'',busy)));
      host.append(results,h('details',{class:'card'},h('summary',{},'Допущения этого экрана'),h('p',{class:'plan-caption'},'Геометрия отображается в координатах сохранённого плана; для нормализованных полос используется масштаб просмотра. Точное размещение маркеров схематично, если в данных есть только признак размещения вне изображения. Демонстрационный экспорт скачивается как JSON с расширением .lbrn2 и явно обозначен как нерабочий файл. Переходы к редактированию и приёму передают идентификатор в параметрах plan и pair.')));
    }
    draw();
    return host;
  }
  App.register({id:'plan',route:'/plans/:id',title:'План гравировки и экспорт',render(ctx){
    const loader=App.load(()=>build(ctx));
    const label=loader.querySelector('.loading-label');if(label)label.textContent='Загружаем план…';
    return loader;
  }});
})();
