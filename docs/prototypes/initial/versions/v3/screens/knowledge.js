(function () {
  'use strict';
  const h = App.h;
  const entity = 'Запись знания';
  const stages = ['Измерено', 'Кандидат', 'Повторено', 'Валидировано', 'Производственное'];
  const labels = {power:'Мощность',frequency:'Частота',speed:'Скорость',pulseDuration:'Длительность импульса',lineInterval:'Интервал линий',passes:'Проходы'};
  const units = {power:'%',frequency:'кГц',speed:'мм/с',pulseDuration:'нс',lineInterval:'мм',passes:''};
  const key = 'titanium.knowledge.view.v1';
  let views = {};
  try { views = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (_) {}
  function remember(id, value) {
    views[id] = {...views[id], ...value};
    try { localStorage.setItem(key, JSON.stringify(views)); } catch (_) {}
  }
  const n = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ru-RU', {maximumFractionDigits:3}) : 'Не определено';
  const lab = value => value ? 'Lab · ' + ['L','a','b'].map(c => c + ': ' + n(value[c])).join(' · ') : 'Нет исходных данных';
  const date = value => {
    if (!value || Number.isNaN(Date.parse(value))) return 'Неизвестно';
    return new Date(value).toLocaleString('ru-RU', {dateStyle:'medium',timeStyle:'short'});
  };
  function color(value) {
    if (!value) return '#e2e5eb';
    const y=(value.L+16)/116, x=y+value.a/500, z=y-value.b/200;
    const f=t => t*t*t>0.008856 ? t*t*t : (t-16/116)/7.787;
    const X=f(x)*0.95047,Y=f(y),Z=f(z)*1.08883;
    return 'rgb(' + [3.2406*X-1.5372*Y-0.4986*Z,-0.9689*X+1.8758*Y+0.0415*Z,0.0557*X-0.204*Y+1.057*Z].map(t => Math.round(Math.max(0,Math.min(1,t<=0.0031308?12.92*t:1.055*Math.pow(t,1/2.4)-0.055))*255)).join(',') + ')';
  }
  function link(text, route) { return h('a',{href:'#'+route},text); }
  function button(text, fn, kind, disabled) { return h('button',{type:'button',class:'btn '+(kind || ''),disabled:!!disabled,onClick:fn},text); }
  function notice(text, kind) { return h('div',{class:'alert '+(kind ? 'alert-'+kind : ''),role:'status'},text); }
  function params(value) {
    return h('dl',{class:'knowledge-parameters'},Object.entries(labels).map(([k,label]) => [h('dt',{},label),h('dd',{},n(value && value[k]) + (units[k] ? ' '+units[k] : ''))]));
  }
  function eligibility(value) {
    return h('div',{},h('span',{class:'badge '+(value && value.allowed ? 'badge-success':'badge-warning')},value ? (value.allowed?'Допущено':'Не допущено'):'Не определено'),h('p',{class:'text-sm muted knowledge-reason'},value && value.reason || 'Результат оценки отсутствует'));
  }
  function context(o) {
    const material=o.materialId ? DB.get('Профиль материала',o.materialId) : null;
    return h('div',{class:'text-sm'},h('div',{},'Материал: ',material ? material.name : 'Неизвестно'),h('div',{},'Партия или лист: ',o.batch || 'Неизвестно'),h('div',{},'Фокус: ',o.focus == null ? 'Неизвестно' : n(o.focus)),h('div',{},'Дата гравировки: ',o.engravedAt || 'Неизвестно'),o.note ? h('div',{},'Примечание: ',o.note):null);
  }
  function evidence(ids) {
    if (!ids || !ids.length) return h('p',{class:'muted'},'Наблюдения-основания отсутствуют');
    return h('div',{class:'table-wrap'},h('table',{class:'table knowledge-evidence'},h('caption',{class:'sr-only'},'Наблюдения-основания записи знания'),h('thead',{},h('tr',{},['Работа или плата','Измеренный Lab','Контекст','Выравнивание','Допуск к модели','Допуск к независимым повторам'].map(t=>h('th',{scope:'col'},t)))),h('tbody',{},ids.map(id=>{
      const o=DB.get('Наблюдение',id);
      if (!o) return h('tr',{},h('td',{colspan:6},'Наблюдение '+id+' не найдено'));
      const p=DB.get('Пара входных файлов',o.pairId);
      const b=p && p.boardId ? DB.get('Калибровочная плата',p.boardId) : null;
      return h('tr',{},h('td',{},link(b ? b.experimentId : p && p.name || o.pairId,'/analysis/'+encodeURIComponent(o.pairId)),h('div',{class:'text-sm muted'},o.id+' · '+(o.regionId || o.layerId)),p && p.lightburnFile ? h('div',{class:'text-sm muted'},p.lightburnFile.name):null),h('td',{},h('span',{class:'swatch',style:{background:color(o.lab)},'aria-hidden':'true'}),h('div',{class:'text-sm'},lab(o.lab))),h('td',{},context(o)),h('td',{},o.alignmentMethod || 'Неизвестно'),h('td',{},eligibility(o.modelEligibility)),h('td',{},eligibility(o.repeatEligibility)));
    }))));
  }
  function metrics(k) {
    return h('div',{class:'knowledge-metrics'},[
      ['Уверенность',n(k.confidence),k.confidenceScale || 'Шкала не определена'],
      ['Ожидаемая ошибка ΔE',n(k.expectedDeltaE),'Демонстрационная оценка'],
      ['Стабильность',k.stability && k.stability.assessed ? k.stability.label || 'Оценена':'Не оценена',k.stability && k.stability.assessed ? 'Разброс: '+n(k.stability.variance):'Недостаточно данных для оценки'],
      ['Допустимые независимые повторы',k.independentRepeats == null ? 'Не определено':n(k.independentRepeats),'Повторная фотография не считается независимой гравировкой']
    ].map(([label,value,help])=>h('div',{class:'knowledge-metric'},h('span',{class:'text-sm muted'},label),h('strong',{},value),h('small',{class:'muted'},help))));
  }
  App.addStyles('.knowledge-screen{display:flex;flex-direction:column;gap:24px}.knowledge-top{display:grid;grid-template-columns:150px minmax(0,1fr);gap:24px;align-items:start}.knowledge-color{height:150px;border:1px solid #0002;border-radius:16px}.knowledge-id{overflow-wrap:anywhere}.knowledge-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:16px;margin-top:24px}.knowledge-metric{padding:16px;background:#f8f9fb;border-radius:12px;display:flex;flex-direction:column;gap:8px}.knowledge-metric strong{font-size:21px;line-height:1.25}.knowledge-parameters{display:grid;grid-template-columns:minmax(130px,1fr) minmax(100px,1fr);gap:8px 16px;margin:0}.knowledge-parameters dt{color:var(--muted);font-size:13px}.knowledge-parameters dd{margin:0;font-weight:550}.knowledge-stages{display:flex;gap:8px;flex-wrap:wrap;padding:0;margin:16px 0;list-style:none}.knowledge-stages li{padding:9px 12px;border-radius:9px;background:#f1f3f6;font-size:13px}.knowledge-stages li[aria-current=step]{background:var(--accent-soft);color:var(--accent);font-weight:650}.knowledge-reason{margin:8px 0 0}.knowledge-evidence{min-width:980px}.knowledge-history{min-width:750px}.knowledge-screen summary{cursor:pointer;font-weight:600;padding:8px 0}.knowledge-screen details>div{margin-top:16px}.knowledge-doubt{display:flex;flex-direction:column;gap:16px}.knowledge-doubt p{margin:0}.knowledge-modal-error{margin-top:16px}.knowledge-limit{margin-top:12px}.knowledge-actions{margin-top:20px}.knowledge-history td{overflow-wrap:anywhere}.knowledge-observation-list{padding-left:20px}.knowledge-observation-list li{margin:8px 0}@media(max-width:1100px){.knowledge-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.knowledge-top{grid-template-columns:1fr}.knowledge-color{height:110px}.knowledge-metrics{grid-template-columns:1fr}.knowledge-parameters{grid-template-columns:1fr 1fr}}');

  function screen(ctx) {
    const id=ctx.params.id;
    const k=ctx.proto.empty ? null : DB.get(entity,id);
    if (!k) return h('section',{class:'empty-state'},h('h2',{},'Запись знания не найдена'),h('p',{},'Откройте запись из карты цветов.'),link('К карте цветов','/colors'));
    const p=DB.get('Профиль лазера',k.profileId);
    const m=DB.list('Модель цветового пространства',{filter:{profileId:k.profileId},pageSize:1000}).items[0];
    const rules=!!(m && m.rules && m.rules.agreed);
    const route='/colors?profileId='+encodeURIComponent(k.profileId);
    const root=h('div',{class:'knowledge-screen'});
    const error=h('div',{hidden:true,class:'alert alert-danger',role:'alert'});
    let retry=null,busy=false;
    const actions=[];
    async function perform(operation,args,message,api) {
      if (busy) return;
      busy=true;
      actions.forEach(b=>b.disabled=true);
      const place=api ? api.body.querySelector('.knowledge-modal-error') : error;
      if(place){place.hidden=true;place.replaceChildren();}
      try {
        await DB.run(operation,...args);
        if (api) api.close(true);
        App.toast(message,'success');
        App.refresh();
      } catch (e) {
        const run=()=>perform(operation,args,message,api);
        retry=run;
        const target=place || error;
        target.hidden=false;
        target.replaceChildren(h('strong',{},'Не удалось сохранить решение'),h('p',{class:'knowledge-reason'},'Стадия и флаг остаются прежними. '+(e.message || 'Повторите попытку.')),button('Повторить',run));
      } finally {
        busy=false;
        actions.forEach(b=>b.disabled=b.dataset.blocked==='true');
      }
    }
    function decision(title,body,label,operation,args,message,danger) {
      const errors=h('div',{class:'alert alert-danger knowledge-modal-error',role:'alert',hidden:true});
      App.modal({title,body:h('div',{},body,errors),actions:[{label:'Отмена',onClick:api=>api.close(null)},{label,kind:danger?'danger':'primary',onClick:api=>perform(operation,args,message,api)}]});
    }
    function action(label,fn,blocked) {
      const b=button(label,fn,'',blocked);
      b.dataset.blocked=String(!!blocked);actions.push(b);return b;
    }
    const approval=action('Утвердить для производства',()=>decision('Утвердить для производства',h('div',{class:'stack'},notice('Ручное утверждение переводит запись в стадию «Производственное». Флаг «Под вопросом» сохраняется, если он установлен.'),params(k.parameters),metrics(k),h('h3',{},'Наблюдения-основания'),evidence(k.observationIds)),'Утвердить','approveProduction',[id,true],'Запись утверждена для производства'),k.stage!=='Валидировано');
    const top=h('section',{class:'card'},h('div',{class:'knowledge-top'},h('div',{},h('div',{class:'knowledge-color',style:{background:color(k.lab)},role:'img','aria-label':'Цветовой образец: '+lab(k.lab)},''),h('p',{class:'text-sm muted knowledge-limit'},'Экранное представление Lab')),h('div',{},h('div',{class:'card-header'},h('h2',{class:'knowledge-id'},k.id),h('span',{class:'badge '+(k.questionable?'badge-warning':'badge-info')},k.questionable?'Под вопросом':k.stage)),h('p',{},lab(k.lab)),h('p',{class:'muted'},p ? p.name+' · Версия '+p.version : 'Версия профиля не найдена'),params(k.parameters))),metrics(k));
    root.append(h('div',{class:'row'},link('К карте цветов',route),h('span',{class:'spacer'}),link('Правила оценки','/profiles?tab=rules&profileId='+encodeURIComponent(k.profileId))),error,top);
    const maturity=h('section',{class:'card'},h('h2',{},'Стадия зрелости'),h('ol',{class:'knowledge-stages','aria-label':'Измерено → Кандидат → Повторено → Валидировано → Производственное'},stages.map(stage=>h('li',{'aria-current':stage===k.stage?'step':null},stage===k.stage?stage+' · Текущая стадия':stage))),h('p',{class:'muted text-sm'},'До стадии «Валидировано» продвижение выполняется системой по согласованным правилам. Производственное утверждение выполняется вручную.'));
    if(!rules) maturity.append(notice('Автоматическая валидация ожидает согласования критериев','warning'));
    else maturity.append(notice(m.rules.specification || 'Критерии качества и независимости согласованы'));
    if(k.independentRepeats==null || k.independentRepeats<Math.max(2,m && m.repeatThreshold || 2)) maturity.append(h('p',{class:'knowledge-limit muted'},'Недостаточно допустимых независимых повторов'));
    if(m) maturity.append(h('p',{class:'text-sm muted knowledge-limit'},'Порог независимых повторов: '+(m.repeatThreshold==null?'Не задано':n(m.repeatThreshold))+' · Допуск отклонения ΔE: '+(m.deltaTolerance==null?'Не задано':n(m.deltaTolerance))+' · Порог дисперсии: '+(m.varianceThreshold==null?'Не задано':n(m.varianceThreshold))));
    maturity.append(h('div',{class:'row knowledge-actions'},approval));
    if(k.stage!=='Валидировано') maturity.append(h('p',{class:'field-help knowledge-limit'},'Утверждение доступно только для стадии «Валидировано».'));
    if(k.stage==='Производственное') {
      maturity.querySelector('.knowledge-actions').append(action('Понизить вручную',()=>{
        const select=h('select',{class:'select','aria-label':'Более низкая стадия',value:views[id] && views[id].downgrade || 'Валидировано'},stages.slice(0,4).map(s=>h('option',{value:s},s)));
        select.addEventListener('change',()=>remember(id,{downgrade:select.value}));
        const body=h('div',{class:'stack'},notice('Понижение изменяет производное знание. Измерения и прежняя история сохраняются.','warning'),h('p',{},'Текущая стадия: '+k.stage),h('label',{class:'field'},h('span',{class:'field-label'},'Новая стадия'),select),h('h3',{},'Связанные доказательства'),evidence(k.doubtObservationIds && k.doubtObservationIds.length ? k.doubtObservationIds:k.observationIds),h('div',{class:'alert alert-danger knowledge-modal-error',hidden:true,role:'alert'}));
        App.modal({title:'Понизить вручную',body,actions:[{label:'Отмена',onClick:api=>api.close(null)},{label:'Подтвердить понижение',kind:'danger',onClick:api=>perform('downgradeKnowledge',[id,select.value,true],'Стадия понижена',api)}]});
      }));
    }
    root.append(maturity);
    if(k.questionable) {
      const doubtIds=k.doubtObservationIds || [];
      const doubt=h('section',{class:'card knowledge-doubt'},h('div',{class:'card-header'},h('h2',{},'Под вопросом'),h('span',{class:'badge badge-warning'},'Стадия не изменена')),notice(k.doubtReason || 'Причина сомнения не указана','warning'),h('p',{},'Допуск отклонения ΔE: '+(m && m.deltaTolerance!=null?n(m.deltaTolerance):'Не задано')));
      const deviations=doubtIds.map(oid=>{
        const o=DB.get('Наблюдение',oid);
        return h('li',{},o ? link(o.id,'/analysis/'+encodeURIComponent(o.pairId)):oid,h('span',{},' · Отклонение от производного цвета ΔE: '+(o && o.lab && k.lab?n(DB.deltaE(o.lab,k.lab)):'Нет исходных данных')));
      });
      doubt.append(h('h3',{},'Наблюдения, вызвавшие сомнение'),doubtIds.length?h('ul',{class:'knowledge-observation-list'},deviations):h('p',{class:'muted'},'Наблюдения, вызвавшие сомнение, не указаны'),evidence(doubtIds),h('div',{class:'row'},action('Подтвердить запись',()=>decision('Подтвердить запись',h('div',{class:'stack'},notice('Снятие флага не изменяет стадию. Действие и ссылки на вызвавшие сомнение наблюдения будут записаны в историю.'),h('p',{},k.doubtReason || 'Причина сомнения не указана'),evidence(doubtIds)),'Снять флаг','clearQuestionable',[id,true],'Флаг снят'))));
      root.append(doubt);
    }
    root.append(notice('Цветная гравировка и цветовой путь исключают параметры под вопросом без включения в конкретный план. Тональный режим может использовать их с предупреждением','warning'));
    const proofs=h('section',{class:'card'},h('h2',{},'Доказательства'),h('p',{class:'muted'},'Измеренный цвет сохраняется неизменяемым. Производный Lab рассчитывается отдельно.'),evidence(k.observationIds));
    root.append(proofs);
    const history=h('details',{class:'card',open:!!(views[id] && views[id].history)},h('summary',{},'История · '+(k.history || []).length+' событий'));
    history.addEventListener('toggle',()=>remember(id,{history:history.open}));
    const events=(k.history || []).slice().reverse();
    history.append(events.length?h('div',{class:'table-wrap'},h('table',{class:'table knowledge-history'},h('caption',{class:'sr-only'},'История переходов и ручных решений'),h('thead',{},h('tr',{},['Дата события','Действие','Прежняя стадия','Новая стадия','Основания','Откат'].map(t=>h('th',{scope:'col'},t)))),h('tbody',{},events.map(e=>{
      const allowed=stages.includes(e.from) && stages.indexOf(e.from)<=stages.indexOf(k.stage) && e.from!==e.to;
      return h('tr',{},h('td',{},date(e.at)),h('td',{},e.type || 'Неизвестно',h('div',{class:'text-sm muted'},e.reason || 'Основание не указано')),h('td',{},e.from || 'Неизвестно'),h('td',{},e.to || 'Неизвестно'),h('td',{},(e.observationIds || []).length ? (e.observationIds || []).map(oid=>{
        const o=DB.get('Наблюдение',oid);
        return h('div',{},o?link(oid,'/analysis/'+encodeURIComponent(o.pairId)):oid);
      }):'Наблюдения не указаны'),h('td',{},action('Откатить переход',()=>decision('Откатить переход',h('div',{class:'stack'},notice('Откат создаёт новый журналируемый переход. Прежняя история и измерения сохраняются.','warning'),h('p',{},'Текущая стадия: '+k.stage),h('p',{},'Целевая стадия: '+e.from),h('p',{class:'text-sm muted'},'Переход от '+date(e.at)+' · '+(e.reason || e.id)),evidence(e.observationIds)),'Выполнить откат','rollbackKnowledge',[id,e.id,true],'Откат записан',true),!allowed),!allowed?h('p',{class:'field-help knowledge-limit'},e.from===e.to?'Стадия в этом событии не изменялась.':'Откат не может повысить текущую стадию.'):null));
    })))):h('div',{class:'muted'},'Переходов пока нет'));
    root.append(history,h('details',{class:'card'},h('summary',{},'Допущения экрана'),h('p',{class:'text-sm muted knowledge-limit'},'Цветовой образец — экранное представление Lab. Отклонения в блоке «Под вопросом» рассчитаны относительно текущего производного Lab; исторический прогноз не подменяется этим значением. Правила оценки открываются с параметрами tab=rules и profileId. Ограничений по ролям нет: доступность действий определяется стадией записи.')));
    return root;
  }
  App.register({id:'knowledge',route:'/knowledge/:id',title:'Знание о цвете',render(ctx){
    if(ctx.proto.error){
      const host=h('div',{});
      const run=()=>{
        host.replaceChildren(h('p',{class:'loading-label',role:'status'},'Загружаем доказательства…'));
        setTimeout(()=>host.replaceChildren(h('section',{class:'error-state',role:'alert'},h('h2',{},'Не удалось сохранить решение'),h('p',{},'Включено состояние ошибки в меню «Прототип». Стадия остаётся прежней. Отключите состояние ошибки и повторите.'),button('Повторить',()=>App.refresh(),'btn-primary'))),350);
      };
      run();return host;
    }
    const host=App.load(()=>screen(ctx));
    const label=host.querySelector('.loading-label');
    if(label)label.textContent='Загружаем доказательства…';
    return host;
  }});
})();
