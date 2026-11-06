(function () {
  'use strict';
  const h = App.h;
  const E = {profile:'Профиль лазера',model:'Модель цветового пространства',target:'Целевой цвет',proposal:'Предложение эксперимента',board:'Калибровочная плата',knowledge:'Запись знания',observation:'Наблюдение',plan:'План гравировки'};
  const key = 'titanium.designer.selection.v1';
  let preference = {};
  try { preference = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (_) {}
  const all = entity => DB.list(entity,{pageSize:100000,sort:'createdAt',dir:'asc'}).items;
  const number = value => Number.isFinite(value) ? value.toLocaleString('ru-RU',{maximumFractionDigits:3}) : 'Не определено';
  const lab = value => value ? 'Lab ' + ['L','a','b'].map(k=>number(value[k])).join(' / ') : 'Нет исходных данных';
  const link = (label,route) => h('a',{class:'btn btn-small',href:'#'+route},label);
  const button = (label,action,primary=false,disabled=false) => h('button',{class:'btn'+(primary?' btn-primary':''),type:'button',disabled,onClick:action},label);
  function remember(profileId) {
    preference.profileId = profileId;
    try { localStorage.setItem(key,JSON.stringify(preference)); } catch (_) { App.toast('Выбор версии сохранён только до закрытия страницы','warning'); }
  }
  function swatch(value) {
    // Цветовая визуализация Lab преобразуется локально в sRGB.
    if (!value) return h('span',{class:'swatch',style:{background:'#eceef2'},'aria-label':'Цвет отсутствует'});
    const fy=(value.L+16)/116, fx=fy+value.a/500, fz=fy-value.b/200;
    const inverse=t=>t*t*t>0.008856?t*t*t:(t-16/116)/7.787;
    const x=inverse(fx)*0.95047,y=inverse(fy),z=inverse(fz)*1.08883;
    const gamma=v=>Math.round(Math.max(0,Math.min(1,v<=0.0031308?12.92*v:1.055*Math.pow(v,1/2.4)-0.055))*255);
    const rgb=[3.2406*x-1.5372*y-0.4986*z,-0.9689*x+1.8758*y+0.0415*z,0.0557*x-0.204*y+1.057*z].map(gamma);
    return h('span',{class:'swatch',style:{background:'rgb('+rgb.join(',')+')'},'aria-label':lab(value)});
  }
  function parameters(p) {
    return h('dl',{class:'designer-vector'},...[
      ['Мощность',number(p?.power)+' %'],['Частота',number(p?.frequency)+' кГц'],['Скорость',number(p?.speed)+' мм/с'],
      ['Длительность импульса',number(p?.pulseDuration)+' нс'],['Интервал линий',number(p?.lineInterval)+' мм'],['Проходы',number(p?.passes)]
    ].map(([label,value])=>h('div',{},h('dt',{},label),h('dd',{},value))));
  }
  function forecast(prediction) {
    if (!prediction || !prediction.lab || !Number.isFinite(prediction.confidence) || !Number.isFinite(prediction.expectedDeltaE) || !prediction.stability) {
      return h('div',{class:'alert'},'Прогноз пока недоступен. Уверенность, ожидаемая ошибка ΔE и стабильность не определены.');
    }
    return h('div',{class:'stack'},h('div',{class:'row'},swatch(prediction.lab),lab(prediction.lab)),
      h('p',{},'Уверенность: '+number(prediction.confidence)+' по шкале от 0 до 1 · Ожидаемая ошибка ΔE: '+number(prediction.expectedDeltaE)),
      h('p',{},'Стабильность: '+(prediction.stability.assessed ? (prediction.stability.label || 'Демонстрационная оценка')+'; разброс '+number(prediction.stability.variance) : 'Не оценена — недостаточно допустимых независимых повторов')));
  }
  function evidence(ids) {
    const rows=(ids||[]).map(id=>DB.get(E.observation,id)).filter(Boolean);
    if (!rows.length) return h('p',{class:'muted'},'Наблюдения-основания отсутствуют');
    return h('div',{class:'designer-evidence'},...rows.map(o=>h('div',{class:'designer-evidence-row'},
      h('a',{href:'#/analysis/'+encodeURIComponent(o.pairId)},o.id),h('span',{},lab(o.lab)),
      h('small',{class:'muted'},'Партия или лист: '+(o.batch||'Неизвестно')+' · Фокус: '+(o.focus==null?'Неизвестно':number(o.focus))),
      h('small',{},'Допуск к модели: '+(o.modelEligibility?.allowed?'Да':'Нет')+' — '+(o.modelEligibility?.reason||'Не определено')))));
  }
  App.addStyles(`
    .designer-screen .designer-targets{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}
    .designer-screen .designer-target{padding:16px;border:1px solid var(--line);border-radius:12px;background:white;display:flex;flex-direction:column;gap:12px;align-items:start}
    .designer-screen .designer-target.selected{border-color:var(--accent);background:var(--accent-soft)}
    .designer-screen .designer-target .swatch{width:64px;height:64px}
    .designer-vector{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin:16px 0}
    .designer-vector dt{font-size:12px;color:var(--muted)}.designer-vector dd{margin:4px 0 0;font-weight:600}
    .designer-evidence{max-height:300px;overflow:auto}.designer-evidence-row{display:flex;flex-direction:column;gap:5px;padding:12px 0;border-bottom:1px solid var(--line)}
    .designer-screen .designer-reasons{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
    .designer-screen .designer-reason{padding:16px;background:#f8f9fb;border-radius:12px}
    .designer-screen .designer-signature{max-height:120px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
    .designer-board{margin-top:16px;padding:16px;border:1px solid var(--line);border-radius:12px}
    .designer-board-grid{overflow:auto;max-height:360px}.designer-board-grid table{border-collapse:separate;border-spacing:4px;font-size:12px;width:100%}.designer-board-grid th{color:var(--muted);font-weight:500}.designer-board-grid td{padding:8px;background:#f0f4f9;border-radius:5px;min-width:62px;text-align:center}.designer-board-grid td.proposed{background:var(--accent-soft);outline:1px solid var(--accent)}
    .designer-board-markers{display:flex;justify-content:space-between;color:var(--muted);font-size:12px;margin:8px 0}
    @media(max-width:600px){.designer-vector{grid-template-columns:repeat(2,minmax(0,1fr))}.designer-screen .designer-reasons{grid-template-columns:1fr}}
  `);
  function build(ctx) {
    const profiles=all(E.profile);
    const root=h('div',{class:'designer-screen stack'});
    if(ctx.proto.empty) {
      root.append(h('section',{class:'empty-state'},h('h2',{},'Добавьте измерения для анализа цветового пространства'),h('p',{},'Предложение следующего эксперимента появится после принятия наблюдений.'),link('Добавить измерения','/ingest')));
      return root;
    }
    const requested=ctx.query.get('profileId')||ctx.query.get('profile');
    const requestedModel=ctx.query.get('modelId')?DB.get(E.model,ctx.query.get('modelId')):null;
    let profileId=profiles.find(p=>p.id===(requested||requestedModel?.profileId||preference.profileId))?.id||profiles[0]?.id;
    let proposal=null, selectedTarget=null, selectedIndex=null, busy=false;
    let actionError=null, retryAction=null;
    const toolbar=h('div',{class:'toolbar'});
    const select=h('select',{class:'select',id:'designer-profile','aria-label':'Версия профиля'},...profiles.map(p=>h('option',{value:p.id,selected:p.id===profileId},p.name+' · версия '+p.version)));
    toolbar.append(h('div',{class:'field'},h('label',{for:'designer-profile'},'Версия профиля'),select),h('span',{class:'spacer'}),link('Карта цветов','/colors'),link('Добавить измерения','/ingest'));
    root.append(toolbar);
    const body=h('div',{class:'stack'});root.append(body);
    function models() { return all(E.model).filter(m=>m.profileId===profileId).at(-1)||null; }
    function targets() { return all(E.target).filter(t=>DB.get(E.plan,t.sourcePlanId)?.profileId===profileId); }
    function latestProposal() { return all(E.proposal).filter(p=>p.profileId===profileId).at(-1)||null; }
    async function perform(label,operation,success,errorText) {
      if(busy)return;
      busy=true;actionError=null;draw(label);
      try { const result=await operation();success(result); }
      catch(error) { actionError=errorText;retryAction=()=>perform(label,operation,success,errorText); }
      finally {busy=false;draw();}
    }
    function showCell(index) {
      selectedIndex=index;draw();
      const cell=proposal.parameters[index];
      const target=cell.targetId?DB.get(E.target,cell.targetId):null;
      const reasonText={ 'Пробел':'Расширение измеренного покрытия цветового пространства.', 'Высокая неопределённость':'Новые измерения нужны для уменьшения неопределённости модели.', 'Нестабильность':'Контрольный эксперимент исследует разброс результата.', 'Целевой цвет':'Проверка параметров связана с недостижимым цветом исходной работы.' };
      App.modal({title:'Предложенный набор '+(index+1),body:h('div',{class:'stack'},
        h('p',{},cell.reason+' · Оценка полезности: '+number(cell.utility)),h('p',{class:'muted'},reasonText[cell.reason]||'Причина указана алгоритмом предложения.'),parameters(cell.parameters),
        target?h('div',{class:'row'},swatch(target.lab),lab(target.lab),link('Исходная работа','/plans/'+encodeURIComponent(target.sourcePlanId))):null,
        forecast(cell.prediction),h('h3',{},'Наблюдения-основания'),evidence(cell.observationIds||DB.get(E.model,proposal.modelId)?.observationIds)),
        actions:[{label:'Закрыть',onClick:api=>api.close()}]});
    }
    function boardDialog() {
      const current=proposal;
      const fields={},errors={};
      const host=h('div',{class:'stack'}),grid=h('div',{class:'grid'}),preview=h('div'),message=h('div',{role:'alert'});
      let boards=null, options=null, signature=null,creating=false;
      [['cellWidth','Ширина ячейки, мм',8],['cellHeight','Высота ячейки, мм',8],['gap','Зазор между ячейками, мм',2]].forEach(([name,label,value])=>{
        const id='designer-'+name;
        fields[name]=h('input',{id,type:'number',step:'any',value,min:name==='gap'?0:undefined,'aria-describedby':id+'-error'});
        errors[name]=h('span',{id:id+'-error',class:'field-error'});
        fields[name].addEventListener('input',()=>{boards=null;signature=null;preview.replaceChildren(h('p',{class:'muted'},'Геометрия изменена. Обновите предпросмотр.'));updateButton();});
        grid.append(h('div',{class:'field'},h('label',{for:id},label),fields[name],errors[name]));
      });
      host.append(h('p',{},'Мощность по столбцам, частота по строкам. Отдельная плата для каждого значения скорости.'),grid,
        h('div',{class:'alert'},'Маркеры и машинный идентификатор включены обязательно и размещены вне сетки.'),message,preview);
      const modal=App.modal({title:'Создать калибровочные платы',body:host,actions:[
        {label:'Отмена',onClick:api=>api.close()},
        {label:'Предпросмотр',onClick:()=>refreshPreview()},
        {label:'Создать планы',kind:'primary',disabled:true,onClick:async api=>{
          if(!boards||signature!==JSON.stringify(values()))return false;
          creating=true;message.textContent='Создаём планы калибровочных плат…';
          try {
            const result=await DB.run('createBoards',options);
            api.close();proposal=DB.get(E.proposal,current.id);draw();
            App.toast('Планы калибровочных плат созданы','success');
            if(result.length===0)App.toast('В доступном диапазоне параметров нет подходящих кандидатов','warning');
          } catch (_) {
            creating=false;message.textContent='Не удалось создать планы калибровочных плат. Повторите создание; предложение параметров сохранено.';
            return false;
          }
        }}
      ]});
      function values(){return Object.fromEntries(Object.entries(fields).map(([k,input])=>[k,input.value.trim()===''?NaN:Number(input.value)]));}
      function updateButton(){modal.element.querySelector('.modal-actions button:last-child').disabled=!boards||creating;}
      function refreshPreview() {
        const geometry=values();let valid=true;message.textContent='';
        Object.keys(fields).forEach(k=>{const ok=Number.isFinite(geometry[k])&&(k==='gap'?geometry[k]>=0:geometry[k]>0);errors[k].textContent=ok?'':'Введите допустимое значение';fields[k].setAttribute('aria-invalid',String(!ok));if(!ok)valid=false;});
        if(!valid){boards=null;updateButton();return;}
        try {
          options=DB.proposalBoardOptions(current.id,geometry);boards=DB.previewBoards(options);signature=JSON.stringify(geometry);
          preview.replaceChildren(h('div',{class:'alert alert-warning'},options.message+'. Дополнительные пересечения не являются отдельно подобранными наборами.'),
            h('p',{class:'muted'},'Плат: '+boards.length+' · Ячеек на плате: '+(boards[0]?.cells.length||0)+' · Создание плат не создаёт наблюдений.'),...boards.map((b,i)=>boardPreview(b,i,current)));
        }catch(e){boards=null;message.textContent=e.message||'Проверьте диапазон параметров';}
        updateButton();
      }
      refreshPreview();
    }
    function boardPreview(board,index,current) {
      const table=h('table',{'aria-label':'Сетка платы, скорость '+number(board.speed)+' мм/с'});
      table.append(h('thead',{},h('tr',{},h('th',{},'Частота / мощность'),...board.powerValues.map(v=>h('th',{},number(v)+' %')))));
      table.append(h('tbody',{},...board.frequencyValues.map((f,row)=>h('tr',{},h('th',{scope:'row'},number(f)+' кГц'),...board.powerValues.map((p,column)=>{
        const proposed=current.parameters.some(c=>c.parameters.power===p&&c.parameters.frequency===f&&c.parameters.speed===board.speed);
        return h('td',{class:proposed?'proposed':'',title:proposed?'Предложенный набор':'Дополнительное пересечение'},'Ячейка '+(row*board.powerValues.length+column+1),h('br'),proposed?'Подобрана':'Пересечение');
      })))));
      return h('section',{class:'designer-board'},h('h3',{},'Плата '+(index+1)+' · '+number(board.speed)+' мм/с'),
        h('p',{class:'muted'},'Размер сетки: '+number(board.geometry.width)+' × '+number(board.geometry.height)+' мм · Ячейки: '+number(board.geometry.cellWidth)+' × '+number(board.geometry.cellHeight)+' мм'),
        h('div',{class:'designer-board-markers'},h('span',{},'▣ Маркер'),h('span',{},'▣ Маркер')),h('div',{class:'designer-board-grid'},table),
        h('div',{class:'designer-board-markers'},h('span',{},'▣ Маркер'),h('span',{},'▣ Маркер')),
        h('small',{class:'muted'},'Машинный идентификатор будет назначен при создании плана. Геометрия маркеров демонстрационная.'));
    }
    function draw(loadingLabel) {
      body.replaceChildren();select.disabled=busy;
      const p=profiles.find(p=>p.id===profileId),m=models(),ts=targets();
      if(loadingLabel)body.append(h('div',{class:'alert',role:'status'},loadingLabel));
      if(actionError)body.append(h('div',{class:'alert alert-danger',role:'alert'},h('p',{},actionError),button('Повторить',()=>retryAction(),false,busy)));
      if(!p){body.append(h('section',{class:'empty-state'},h('h2',{},'Сначала настройте профиль лазера'),link('Профили','/profiles')));return;}
      body.append(h('section',{class:'card'},h('div',{class:'card-header'},h('h2',{},'Следующий физический эксперимент'),h('span',{class:'badge badge-info'},'Офлайн-подбор')),
        h('p',{class:'muted'},'Подбор использует измерения всех совместимых источников. При одинаковой базе и фиксированном зерне предложение одинаково.'),
        h('div',{class:'row'},h('span',{},'Версия профиля: '+p.version),h('span',{},'Версия модели: '+(m?.version||'Не определено')),h('span',{},'Наблюдений: '+(m?.observationIds?.length||0))),
        h('div',{class:'designer-reasons'},
          h('div',{class:'designer-reason'},h('strong',{},'Пробелы покрытия'),h('p',{class:'text-sm'},m?.uncertainty?.map(x=>x.label+' — '+number(x.value)).join('; ')||'Расчётные области не определены')),
          h('div',{class:'designer-reason'},h('strong',{},'Неопределённость'),h('p',{class:'text-sm'},m?.uncertainty?.length?'Области высокой неопределённости требуют новых измерений.':'Оценка неопределённости отсутствует')),
          h('div',{class:'designer-reason'},h('strong',{},'Нестабильные области'),h('p',{class:'text-sm'},m?.unstableRegions?.map(x=>x.label+' · разброс '+number(x.variance)).join('; ')||'Нестабильные области не выявлены')))));
      const targetSection=h('section',{class:'card'},h('h2',{},'Цели из недостижимых цветов'));
      if(!ts.length)targetSection.append(h('p',{class:'muted'},'Нет недостижимых цветов из работ'),h('p',{},'Подбор по пробелам и неопределённости остаётся доступен.'));
      else targetSection.append(h('div',{class:'designer-targets'},...ts.map(t=>{
        const plan=DB.get(E.plan,t.sourcePlanId);
        return h('article',{class:'designer-target'+(selectedTarget===t.id?' selected':'')},swatch(t.lab),h('strong',{},lab(t.lab)),h('small',{class:'muted'},t.id+' · Исходный цвет: '+t.sourceColorId),
          button(selectedTarget===t.id?'Снять выделение':'Выбрать целевой цвет',()=>{selectedTarget=selectedTarget===t.id?null:t.id;draw();},false,busy),
          h('a',{href:'#/plans/'+encodeURIComponent(t.sourcePlanId)},'Исходная работа'+(plan?' — '+plan.name:'')),
          h('button',{type:'button',class:'btn btn-small btn-danger',disabled:busy,onClick:()=>App.removeRecord(E.target,t,()=>{if(selectedTarget===t.id)selectedTarget=null;draw();})},'Удалить целевой цвет'));
      })));
      body.append(targetSection);
      if(!m?.observationIds?.length){body.append(h('section',{class:'empty-state'},h('h2',{},'Добавьте измерения для анализа цветового пространства'),link('Добавить измерения','/ingest')));return;}
      body.append(h('div',{class:'row'},button('Предложить плату',()=>perform('Выбираем параметры следующего эксперимента…',()=>DB.run('proposeExperiment',profileId,1729),result=>{proposal=result;selectedIndex=null;App.toast('Предложение сформировано','success');},'Не удалось сформировать предложение'),true,busy),h('span',{class:'muted'},'Фиксированное зерно: 1729')));
      const proposals=all(E.proposal).filter(p=>p.profileId===profileId);
      body.append(h('details',{class:'card'},h('summary',{},'Сохранённые предложения · '+proposals.length),
        proposals.length?proposals.map(p=>h('div',{class:'row',style:{padding:'12px 0'}},
          button('Открыть предложение '+p.id,()=>{proposal=p;selectedIndex=null;draw();},false,busy),
          h('button',{type:'button',class:'btn btn-small btn-danger',disabled:busy,'aria-label':'Удалить предложение '+p.id,onClick:()=>App.removeRecord(E.proposal,p,()=>{proposal=latestProposal();selectedIndex=null;draw();})},'Удалить предложение')))
          :h('p',{class:'muted'},'Сохранённых предложений нет.')));
      if(!proposal)return;
      const proposalModel=DB.get(E.model,proposal.modelId);
      const info=h('section',{class:'card stack'},h('div',{class:'card-header'},h('h2',{},'Предложение '+proposal.id),h('span',{class:'badge'},'Демонстрационный результат')),
        h('p',{},'Версия модели: '+(proposal.modelVersion||proposalModel?.version||'Не определено')+' · Версия профиля: '+p.version+' · Зерно: '+proposal.seed));
      const signature=h('details',{},h('summary',{},'Использованное состояние базы'),h('pre',{class:'designer-signature'},proposal.baseSignature||'Не определено'));
      info.append(signature);
      if(!proposal.parameters?.length)info.append(h('p',{},'В доступном диапазоне параметров нет подходящих кандидатов'));
      else {
        if(selectedTarget)info.append(h('p',{role:'status'},proposal.parameters.some(c=>c.targetId===selectedTarget)?'Выделены наборы выбранного целевого цвета.':'В текущем предложении нет наборов для выбранного целевого цвета. Сформируйте новое предложение.'));
        info.append(h('div',{class:'table-wrap'},h('table',{class:'table'},h('thead',{},h('tr',{},...['Набор','Мощность, %','Частота, кГц','Скорость, мм/с','Причина','Полезность','Прогноз'].map(t=>h('th',{scope:'col'},t)))),
          h('tbody',{},...proposal.parameters.map((c,i)=>h('tr',{class:selectedIndex===i||(selectedTarget&&c.targetId===selectedTarget)?'selected':''},
            h('td',{},button('Набор '+(i+1),()=>showCell(i),false,busy)),h('td',{},number(c.parameters.power)),h('td',{},number(c.parameters.frequency)),h('td',{},number(c.parameters.speed)),
            h('td',{},h('span',{class:'badge'},c.reason),c.targetId?h('small',{class:'muted'},' · '+c.targetId):null),h('td',{},number(c.utility)),
            h('td',{},c.prediction?forecast(c.prediction):'Прогноз пока недоступен')))))));
        info.append(button('Создать калибровочные платы',boardDialog,true,busy));
      }
      const created=(proposal.boardIds||[]).map(id=>DB.get(E.board,id)).filter(Boolean);
      if(created.length)info.append(h('div',{class:'alert alert-success'},h('p',{},'Планы калибровочных плат созданы'),h('div',{class:'row'},...created.map(b=>link('Открыть план платы '+b.experimentId,'/plans/'+encodeURIComponent(b.planId))))));
      if(proposal.explanation)info.append(h('section',{},h('h3',{},'Пояснение и гипотезы'),h('p',{},typeof proposal.explanation==='string'?proposal.explanation:proposal.explanation.text||'Пояснение отсутствует')));
      body.append(info,h('details',{class:'card'},h('summary',{},'Допущения экрана'),h('p',{class:'muted'},'Для подбора используется фиксированное зерно 1729. Геометрия новой платы по умолчанию: ячейка 8 × 8 мм, зазор 2 мм. Серия строится как декартова сетка: дополнительные пересечения отдельно отмечены. Адаптер языковой модели в API не предусмотрен; получение пояснения недоступно. Цветовые образцы Lab показаны локальным преобразованием в sRGB и могут выходить за цветовой охват экрана.')));
    }
    proposal=latestProposal();
    select.addEventListener('change',()=>{profileId=select.value;remember(profileId);proposal=latestProposal();selectedTarget=null;selectedIndex=null;actionError=null;draw();});
    draw();return root;
  }
  App.register({id:'designer',route:'/designer',title:'Планировщик экспериментов',render(ctx){
    const host=App.load(()=>build(ctx));
    const label=host.querySelector('.loading-label');if(label)label.textContent='Выбираем параметры следующего эксперимента…';
    return host;
  }});
})();
