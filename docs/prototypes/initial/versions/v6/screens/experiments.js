(function () {
  'use strict';
  const h = App.h;
  const E = {profile:'Профиль лазера',board:'Калибровочная плата',pair:'Пара входных файлов',observation:'Наблюдение'};
  const key = 'titanium.experiments.screen.v1';
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (_) {}
  const state = {profile:saved.profile || '',type:saved.type || 'Все',q:saved.q || '',sort:saved.sort || 'createdAt',dir:saved.dir || 'desc',page:1};
  const persist = () => { try { localStorage.setItem(key,JSON.stringify(state)); } catch (_) { App.toast('Настройки списка доступны до закрытия страницы.','warning'); } };
  const all = entity => DB.list(entity,{pageSize:100000,sort:'createdAt',dir:'desc'}).items;
  const link = (label,route) => h('a',{class:'btn btn-small',href:'#'+route},label);
  const button = (label,fn,kind='',attrs={}) => h('button',{type:'button',class:'btn '+kind,onClick:fn,...attrs},label);
  const number = value => value == null ? 'Неизвестно' : Number(value).toLocaleString('ru-RU',{maximumFractionDigits:4});
  const date = value => value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleDateString('ru-RU') : 'Неизвестно';
  const file = value => value?.name || 'Не прикреплён';
  function status(value) { return h('span',{class:'badge '+(value==='Принята'?'badge-success':value==='Ошибка'?'badge-danger':value==='Требует исправления'?'badge-warning':'badge-info')},value); }
  function parameters(p) {
    return h('dl',{class:'ex-parameters'},[['Мощность',number(p?.power)+' %'],['Частота',number(p?.frequency)+' кГц'],['Скорость',number(p?.speed)+' мм/с'],['Длительность импульса',number(p?.pulseDuration)+' нс'],['Интервал линий',number(p?.lineInterval)+' мм'],['Проходы',number(p?.passes)]].map(([name,value])=>h('div',{},h('dt',{},name),h('dd',{},value))));
  }
  DB.experimentsRows = function () {
    const boards = all(E.board), pairs = all(E.pair), observations = all(E.observation);
    const rows = boards.map(b => {
      const related = pairs.filter(p=>p.boardId===b.id);
      return {id:b.id,name:b.experimentId || b.id,subtitle:b.name || 'Калибровочная плата',type:'Платы',profileId:b.profileId,lightburnFile:b.lightburnFile,photo:null,engravedAt:null,status:related.length?'Определение платы':'Ожидает файлов',count:observations.filter(o=>related.some(p=>p.id===o.pairId)).length,createdAt:b.createdAt,board:b};
    });
    pairs.forEach(p=>rows.push({id:p.id,name:p.name || p.id,subtitle:p.id,type:p.kind || (p.boardId?'Платы':'Импортированные работы'),profileId:p.profileId,lightburnFile:p.lightburnFile,photo:p.photo,engravedAt:p.context?.engravedAt,status:p.status,count:observations.filter(o=>o.pairId===p.id).length,createdAt:p.createdAt,pair:p}));
    return rows;
  };
  App.addStyles(`
    .ex-screen{display:flex;flex-direction:column;gap:24px}.ex-screen .toolbar{margin:0}.ex-process{display:flex;flex-wrap:wrap;gap:8px;align-items:center;font-size:12px;color:var(--muted);padding:16px 20px;background:#fff;border:1px solid var(--line);border-radius:16px}.ex-process span{white-space:nowrap}.ex-process b{color:var(--accent);font-weight:550}.ex-count{font-size:13px;color:var(--muted)}.ex-search{flex:1;min-width:180px!important}.ex-title{display:flex;flex-direction:column;align-items:flex-start;gap:4px}.ex-title button{font-weight:600;text-align:left;padding:0;border:0;color:var(--accent);background:none}.ex-title small{color:var(--muted)}.ex-file{max-width:180px;overflow-wrap:anywhere}.ex-grid-wrap{overflow:auto;padding:16px;background:#f7f8fa;border:1px solid var(--line);border-radius:12px}.ex-grid{display:grid;gap:6px;width:max-content;min-width:100%;align-items:stretch}.ex-cell{min-width:70px;min-height:62px;padding:8px;background:white;border:1px solid #cbd1da;border-radius:8px;color:var(--text);font-size:12px}.ex-cell[aria-pressed=true]{background:var(--accent-soft);border-color:var(--accent);box-shadow:0 0 0 1px var(--accent)}.ex-axis{display:flex;align-items:center;justify-content:center;padding:8px;font-size:12px;font-weight:600;color:var(--muted)}.ex-marker{width:16px;height:16px;border:3px solid var(--text);display:inline-block;background:#fff;margin-right:8px}.ex-parameters{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0}.ex-parameters div{padding:12px;background:#f7f8fa;border-radius:10px}.ex-parameters dt{font-size:12px;color:var(--muted)}.ex-parameters dd{margin:4px 0 0;font-weight:600}.ex-modal .field{margin-bottom:12px}.ex-preview{display:flex;flex-direction:column;gap:16px}.ex-note{font-size:13px;color:var(--muted)}.ex-screen .table{min-width:1020px}.ex-summary{display:flex;gap:24px;flex-wrap:wrap}.ex-summary strong{display:block;font-size:24px;color:var(--text)}.ex-modal .form-actions{margin-top:16px}.ex-modal details summary{cursor:pointer;color:var(--accent)}@media(max-width:600px){.ex-parameters{grid-template-columns:1fr}.ex-screen .toolbar>*{width:100%}.ex-summary{gap:16px}.ex-cell{min-width:60px}.ex-process{padding:14px}}
  `);
  function boardGrid(board,onSelect,selected) {
    const grid = h('div',{class:'ex-grid',style:{gridTemplateColumns:`70px repeat(${board.powerValues.length},minmax(70px,1fr))`},'aria-label':'Сетка: мощность по столбцам, частота по строкам'});
    grid.append(h('div',{class:'ex-axis'},'кГц / %'));
    board.powerValues.forEach(p=>grid.append(h('div',{class:'ex-axis'},number(p)+' %')));
    board.frequencyValues.forEach((f,row)=>{
      grid.append(h('div',{class:'ex-axis'},number(f)+' кГц'));
      board.powerValues.forEach((p,column)=>{
        const cell = board.cells.find(c=>c.row===row&&c.column===column);
        if (!cell) { grid.append(h('div',{class:'ex-cell'},'Нет ячейки')); return; }
        grid.append(button(cell.id,()=>onSelect(cell),'ex-cell',{'aria-pressed':selected===cell.id,'aria-label':`${cell.id}: мощность ${number(p)} %, частота ${number(f)} кГц`}));
      });
    });
    return h('div',{class:'ex-grid-wrap'},grid);
  }
  function boardPanel(board) {
    let selected = board.cells[0];
    const body = h('div',{class:'stack ex-modal'});
    const draw = () => {
      const profile = DB.get(E.profile,board.profileId);
      const pairs = all(E.pair).filter(p=>p.boardId===board.id);
      const g = board.geometry || {};
      body.replaceChildren(
        h('p',{class:'muted'},board.name || 'Калибровочная плата'),
        h('div',{class:'row'},status('Определение платы'),h('span',{},'Версия профиля: '+(profile?.version || 'Неизвестно')),h('span',{},'Скорость: '+number(board.speed)+' мм/с')),
        boardGrid(board,cell=>{selected=cell;draw();},selected?.id),
        h('p',{class:'ex-note'},'Выберите ячейку для просмотра полного набора параметров. Это параметры определения платы; параметры наблюдений читаются из фактически использованного файла LightBurn.'),
        h('section',{},h('h3',{},selected?'Ячейка '+selected.id:'Нет ячеек'),selected?parameters(selected.parameters):null,selected?h('p',{class:'ex-note'},`Геометрия ячейки: x=${number(selected.geometry?.x)}, y=${number(selected.geometry?.y)}, ширина ${number(selected.geometry?.width)} мм, высота ${number(selected.geometry?.height)} мм`):null),
        h('section',{},h('h3',{},'Исходное определение'),h('p',{},`Размер платы: ${number(g.width)} × ${number(g.height)} мм. Ячейки: ${number(g.cellWidth)} × ${number(g.cellHeight)} мм. Зазор: ${number(g.gap)} мм.`),h('p',{},'Маркеры: включены · Машинный идентификатор: '+(board.markers?.machineId || board.experimentId)),h('p',{class:'ex-note'},'Маркеры и идентификатор размещены вне сетки и гравируются вместе с ней.'),h('p',{},'Файл LightBurn: '+file(board.lightburnFile)),h('div',{class:'row'},board.planId?link('Открыть план','/plans/'+encodeURIComponent(board.planId)):null,board.proposalId?link('Предложение планировщика','/designer?proposal='+encodeURIComponent(board.proposalId)):null)),
        h('section',{},h('h3',{},'Связанные входные пары'),pairs.length?h('div',{class:'stack'},pairs.map(p=>h('div',{class:'alert'},h('div',{class:'row'},link(p.name || p.id,p.status==='Принята'?'/analysis/'+encodeURIComponent(p.id):'/ingest?pair='+encodeURIComponent(p.id)),status(p.status)),h('p',{class:'ex-note'},file(p.lightburnFile)+' · '+file(p.photo))))):h('p',{class:'muted'},'Пары файлов ещё не добавлены. Создание платы не создаёт измерений.')),
        board.targetIds?.length?h('p',{class:'ex-note'},'Целевые цвета: '+board.targetIds.join(', ')):null
      );
    };
    draw();
    App.modal({title:board.experimentId || 'Калибровочная плата',body,actions:[{label:'Закрыть',onClick:api=>api.close()}]});
  }
  function createBoard(profiles,onCreated) {
    if (!profiles.length) return;
    let preview = null, busy = false, api;
    const body = h('div',{class:'ex-modal'});
    const fields = {}, errors = {};
    const profileSelect = h('select',{class:'select',id:'ex-create-profile'},profiles.map(p=>h('option',{value:p.id,selected:p.id===(state.profile || profiles[0].id)},'Версия '+p.version+' — '+p.name)));
    const ranges = h('p',{class:'field-help'});
    const previewHost = h('div',{class:'ex-preview','aria-live':'polite'});
    const message = h('div',{'aria-live':'polite'});
    const create = button('Создать планы',save,'btn-primary',{disabled:true});
    const previewButton = button('Предпросмотр',makePreview);
    const cancel = button('Отмена',()=>{if(!busy)api.close();});
    function field(id,label,value,help) {
      const input = h('input',{id:'ex-create-'+id,value,type:'text',inputmode:'decimal',onInput:invalidate});
      const err = h('span',{class:'field-error',id:'ex-error-'+id,hidden:true});
      input.setAttribute('aria-describedby','ex-error-'+id);
      fields[id]=input;errors[id]=err;
      return h('div',{class:'field'},h('label',{for:input.id},label),input,help?h('span',{class:'field-help'},help):null,err);
    }
    function invalidate() { preview=null;create.disabled=true;previewHost.replaceChildren();message.replaceChildren(); }
    function showRanges() {
      const p=profiles.find(p=>p.id===profileSelect.value);
      ranges.textContent=p.axes.map(a=>`${a.name}: ${number(a.min)}–${number(a.max)} ${a.unit}`).join(' · ');
      invalidate();
    }
    profileSelect.addEventListener('change',showRanges);
    const clearErrors = () => Object.keys(errors).forEach(k=>{errors[k].hidden=true;fields[k].removeAttribute('aria-invalid');});
    function errorAt(id,text) { errors[id].textContent=text;errors[id].hidden=false;fields[id].setAttribute('aria-invalid','true'); }
    function parseList(value) {
      return value.trim().split(/[;\s]+/).filter(Boolean).map(s=>Number(s.replace(',','.')));
    }
    function options() {
      clearErrors();
      const p=profiles.find(p=>p.id===profileSelect.value);
      const result={profileId:p.id,geometry:{}};
      let invalid=false;
      [['powerValues','power'],['frequencyValues','frequency'],['speeds','speed']].forEach(([id,axisKey])=>{
        const values=parseList(fields[id].value), axis=p.axes.find(a=>a.key===axisKey);
        if(!values.length||new Set(values).size!==values.length||values.some(v=>!Number.isFinite(v)||v<axis.min||v>axis.max)) {errorAt(id,'Проверьте диапазон параметров');invalid=true;}
        result[id]=values;
      });
      ['cellWidth','cellHeight','gap'].forEach(id=>{
        const raw=fields[id].value.trim(), v=Number(raw.replace(',','.'));
        if(!raw||!Number.isFinite(v)||(id==='gap'?v<0:v<=0)) {errorAt(id,id==='gap'?'Ячейки пересекаются':'Введите положительный размер');invalid=true;}
        result.geometry[id]=v;
      });
      if(invalid) { body.querySelector('[aria-invalid=true]')?.focus();return null; }
      return result;
    }
    function drawPreview(boards) {
      previewHost.replaceChildren(h('h3',{},'Предпросмотр серии'),h('p',{class:'ex-note'},'Мощность — по столбцам, частота — по строкам. Отдельная плата для каждого значения скорости.'),...boards.map((b,i)=>h('section',{class:'alert'},h('h3',{},`Плата ${i+1} · ${number(b.speed)} мм/с`),boardGrid(b,cell=>{App.modal({title:'Ячейка '+cell.id,body:parameters(cell.parameters),actions:[{label:'Закрыть',onClick:a=>a.close()}]});}),h('p',{class:'ex-note'},`${b.cells.length} ячеек · ${number(b.geometry.width)} × ${number(b.geometry.height)} мм`),h('p',{},h('span',{class:'ex-marker','aria-hidden':'true'}),'Маркеры и машинный идентификатор включены'))));
    }
    async function makePreview() {
      const opts=options();if(!opts)return;
      busy=true;previewButton.disabled=true;create.disabled=true;cancel.disabled=true;message.replaceChildren(h('p',{role:'status'},'Строим сетку платы…'));
      try { const boards=await DB.run('previewBoards',opts);preview=opts;drawPreview(boards);message.replaceChildren();create.disabled=false; }
      catch(e) {preview=null;message.replaceChildren(h('p',{class:'field-error',role:'alert'},e.message || 'Проверьте диапазон параметров'));}
      finally {busy=false;previewButton.disabled=false;cancel.disabled=false;}
    }
    async function save() {
      if(!preview||busy)return;
      const opts=options();if(!opts||JSON.stringify(opts)!==JSON.stringify(preview)){invalidate();return;}
      busy=true;body.querySelectorAll('input,select,button').forEach(el=>el.disabled=true);message.replaceChildren(h('p',{role:'status'},'Создаём планы плат…'));
      try {const result=await DB.run('createBoards',opts);api.close();App.toast('Планы плат созданы','success');onCreated(result);}
      catch(e) {message.replaceChildren(h('div',{class:'alert alert-danger',role:'alert'},h('p',{},e.message || 'Не удалось создать планы плат'),h('p',{},'Введённые значения сохранены. Повторите создание.')));}
      finally {busy=false;body.querySelectorAll('input,select,button').forEach(el=>el.disabled=false);create.disabled=!preview;}
    }
    body.append(h('div',{class:'field'},h('label',{for:'ex-create-profile'},'Версия профиля'),profileSelect,ranges),
      h('div',{class:'grid'},field('powerValues','Значения мощности, %','24; 31; 38','Разделяйте значения точкой с запятой или пробелом.'),field('frequencyValues','Значения частоты, кГц','40; 50'),field('speeds','Список скоростей, мм/с','700; 900','Одна плата на каждую скорость.'),field('cellWidth','Ширина ячейки, мм','8'),field('cellHeight','Высота ячейки, мм','8'),field('gap','Зазор между ячейками, мм','2')),
      h('div',{class:'alert'},h('label',{class:'check'},h('input',{type:'checkbox',checked:true,disabled:true}),'Маркеры и машинный идентификатор'),h('p',{class:'ex-note'},'Обязательны для калибровочной платы. Отключить нельзя.')),
      message,h('div',{class:'form-actions'},previewButton,create,cancel),previewHost,
      h('details',{},h('summary',{},'Допущения экрана'),h('p',{class:'ex-note'},'Размеры задаются в миллиметрах. Положительные ширина и высота и неотрицательный зазор исключают пересечения прямоугольных ячеек. Значения списков не повторяются. Формат маркеров и машинного идентификатора демонстрационный.')));
    showRanges();
    api=App.modal({title:'Создать плату',body});
  }
  function render(ctx) {
    const host=h('div',{});
    let attempt=0;
    function load() {
      const token=++attempt;
      host.setAttribute('aria-busy','true');
      host.replaceChildren(h('p',{class:'loading-label',role:'status'},'Загружаем эксперименты…'),h('div',{class:'skeleton skeleton-block','aria-hidden':'true'}));
      setTimeout(()=>{
        if(token!==attempt)return;
        try {
          if(ctx.proto.error)throw new Error('Ошибка прототипа');
          draw();
        } catch (_) {
          host.replaceChildren(h('section',{class:'error-state',role:'alert'},h('h2',{},'Не удалось загрузить эксперименты'),h('p',{},ctx.proto.error?'Отключите состояние ошибки в меню «Прототип» и повторите загрузку.':'Сохранённые данные остаются доступными.'),button('Повторить',load,'btn-primary')));
        } finally {host.removeAttribute('aria-busy');}
      },350);
    }
    function draw(created) {
      const profiles=all(E.profile).sort((a,b)=>b.version-a.version);
      if(state.profile&&!profiles.some(p=>p.id===state.profile))state.profile='';
      const rows=ctx.proto.empty?[]:DB.experimentsRows();
      const root=h('div',{class:'ex-screen'});
      const process=['Эксперимент','Гравировка','Фотография','Измерение','Сравнение','Обновление модели','Следующий эксперимент'];
      root.append(h('div',{class:'ex-process','aria-label':'Замкнутый цикл'},process.flatMap((s,i)=>[i?h('span',{'aria-hidden':'true'},'→'):null,i===0?h('b',{},s):h('span',{},s)])));
      if(created?.length)root.append(h('section',{class:'alert alert-success',role:'status'},h('h3',{},'Планы плат созданы'),h('div',{class:'row'},created.map(({board,plan})=>link(board.experimentId+' · '+number(board.speed)+' мм/с','/plans/'+encodeURIComponent(plan.id))))));
      const createAction=()=>createBoard(profiles,result=>draw(result));
      root.append(h('div',{class:'toolbar'},button('Создать плату',createAction,'btn-primary',{disabled:!profiles.length}),link('Добавить наблюдение','/ingest'),h('span',{class:'spacer'}),link('Спланировать следующий эксперимент','/designer')));
      if(!profiles.length)root.append(h('div',{class:'permission-restricted'},h('p',{},'Сначала настройте профиль лазера'),link('Профили','/profiles')));
      if(!rows.length) {
        root.append(h('section',{class:'empty-state'},h('h2',{},'Пока нет экспериментов'),h('p',{},'Создайте калибровочную плату или добавьте пару файла LightBurn и фотографии со стенда.'),h('div',{class:'row'},button('Создать плату',createAction,'btn-primary',{disabled:!profiles.length}),link('Добавить наблюдение','/ingest'))));
        host.replaceChildren(root);return;
      }
      const tableHost=h('div',{});
      const profileSelect=h('select',{class:'select',id:'ex-profile',onChange:event=>{state.profile=event.target.value;state.page=1;persist();updateTable();}},h('option',{value:''},'Все версии'),profiles.map(p=>h('option',{value:p.id,selected:state.profile===p.id},'Версия '+p.version)));
      const typeSelect=h('select',{class:'select',id:'ex-type',onChange:event=>{state.type=event.target.value;state.page=1;persist();updateTable();}},['Все','Платы','Готовые работы','Импортированные работы'].map(t=>h('option',{value:t,selected:state.type===t},t)));
      root.append(h('section',{class:'card'},h('div',{class:'card-header'},h('h2',{},'Эксперименты и наблюдения'),h('span',{class:'ex-count'},'Демонстрационные данные')),h('div',{class:'toolbar'},h('div',{class:'field ex-search'},h('label',{for:'ex-search'},'Поиск'),h('input',{class:'input',type:'search',id:'ex-search',value:state.q,placeholder:'Название, идентификатор или имя файла',onInput:event=>{state.q=event.target.value;state.page=1;persist();updateTable();}})),h('div',{class:'field'},h('label',{for:'ex-profile'},'Версия профиля'),profileSelect),h('div',{class:'field'},h('label',{for:'ex-type'},'Тип'),typeSelect)),h('p',{class:'ex-note'},'Определения плат и входные пары показаны отдельно. Фильтры не меняют вес наблюдений.'),tableHost));
      function updateTable() {
        let filtered=rows.filter(r=>(!state.profile||r.profileId===state.profile)&&(state.type==='Все'||r.type===state.type));
        const q=state.q.trim().toLocaleLowerCase('ru-RU');
        if(q)filtered=filtered.filter(r=>[r.id,r.name,r.subtitle,file(r.lightburnFile),file(r.photo)].join(' ').toLocaleLowerCase('ru-RU').includes(q));
        filtered.sort((a,b)=>{const av=a[state.sort]??'',bv=b[state.sort]??'';return (typeof av==='number'&&typeof bv==='number'?av-bv:String(av).localeCompare(String(bv),'ru',{numeric:true}))*(state.dir==='asc'?1:-1);});
        const pages=Math.max(1,Math.ceil(filtered.length/8));state.page=Math.max(1,Math.min(state.page,pages));
        const shown=filtered.slice((state.page-1)*8,state.page*8);
        const sortHead=(label,field)=>h('th',{scope:'col','aria-sort':state.sort===field?(state.dir==='asc'?'ascending':'descending'):'none'},button(label+(state.sort===field?(state.dir==='asc'?' ↑':' ↓'):''),()=>{state.dir=state.sort===field&&state.dir==='asc'?'desc':'asc';state.sort=field;persist();updateTable();}));
        const open=r=>{if(r.board)boardPanel(r.board);else App.navigate(r.pair.status==='Принята'?'/analysis/'+encodeURIComponent(r.id):'/ingest?pair='+encodeURIComponent(r.id));};
        tableHost.replaceChildren(h('p',{class:'ex-count',role:'status'},'Найдено записей: '+filtered.length));
        if(!shown.length) { tableHost.append(h('section',{class:'empty-state'},h('h3',{},'По выбранным условиям ничего не найдено'),button('Сбросить поиск и фильтры',()=>{state.q='';state.profile='';state.type='Все';state.page=1;persist();draw();})));return; }
        tableHost.append(h('div',{class:'table-wrap'},h('table',{class:'table'},h('caption',{class:'sr-only'},'Определения калибровочных плат и пары входных файлов'),h('thead',{},h('tr',{},sortHead('Эксперимент или работа','name'),sortHead('Тип','type'),h('th',{scope:'col'},'Версия профиля'),h('th',{scope:'col'},'Файл LightBurn'),h('th',{scope:'col'},'Фотография'),sortHead('Дата гравировки','engravedAt'),sortHead('Состояние обработки','status'),sortHead('Принятые наблюдения','count'))),h('tbody',{},shown.map(r=>{
          const p=profiles.find(p=>p.id===r.profileId);
          return h('tr',{},h('td',{},h('div',{class:'ex-title'},button(r.name,()=>open(r)),h('small',{},r.subtitle))),h('td',{},r.type),h('td',{},p?'Версия '+p.version:'Неизвестно'),h('td',{class:'ex-file'},file(r.lightburnFile)),h('td',{class:'ex-file'},r.board?'В связанных парах':file(r.photo)),h('td',{},r.board?'В связанных парах':date(r.engravedAt)),h('td',{},status(r.status)),h('td',{},number(r.count)));
        })))));
        tableHost.append(h('div',{class:'pagination'},h('span',{},`Страница ${state.page} из ${pages}`),button('Назад',()=>{state.page--;updateTable();},'btn-small',{disabled:state.page===1}),button('Далее',()=>{state.page++;updateTable();},'btn-small',{disabled:state.page===pages})));
      }
      updateTable();host.replaceChildren(root);
    }
    load();return host;
  }
  App.register({id:'experiments',route:'/experiments',title:'Эксперименты и наблюдения',render});
})();
