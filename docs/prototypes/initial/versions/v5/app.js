/**
 * API оболочки «Цвет титана». Все экраны подключаются после app.js.
 * App.register({id,route,title,render(ctx)}): id совпадает с App.plan;
 * route поддерживает :id и другие сегменты-параметры. render возвращает
 * Element, доверенную HTML-строку или Promise такого результата.
 * ctx = {params: объект декодированных сегментов, query: URLSearchParams,
 * user: {id,name,role,permissions}, proto: {empty,error}}.
 * При смене маршрута, пользователя и режима прототипа render вызывается заново.
 * ctx.proto.empty: экран сам показывает предусмотренное пустое состояние,
 * не изменяя DB. ctx.proto.error обрабатывается автоматически через App.load.
 * Рекомендуемый render: ctx => App.load(() => построитьЭкран(ctx)).
 * App.load(fn): сразу возвращает HTMLElement со скелетоном, через минимум
 * 350 мс вызывает fn, поддерживает Promise; ошибка показывает карточку
 * с «Повторить». fn вызывается заново при повторе. Не используйте fn для
 * необратимых записей: загрузка и повтор должны только читать данные.
 * App.h(tag,attrs,...children): DOM; дети — узлы, строки, числа, массивы.
 * Строковые дети экранируются. null/undefined/boolean игнорируются.
 * attrs: class/className, text, dataset, style (объект), обычные атрибуты,
 * DOM-свойства value/checked/disabled/selected, события onClick/onInput и т. п.
 * App.navigate('/analysis/идентификатор?ключ=значение') добавляет запись истории.
 * App.toast(message,kind='info'): kind info/success/error/warning;
 * возвращает функцию закрытия. App.addStyles(css) добавляет правила экрана.
 * App.modal({title,body,actions}): body — узел или доверенная HTML-строка;
 * actions — [{label,kind:'primary'|'danger'|'secondary',disabled:false,
 * onClick(api,event),close:false}]. api={element,body,close(value),result}.
 * result — Promise результата закрытия; Escape, крестик и фон возвращают null.
 * onClick может быть async; на время выполнения действия блокируются.
 * По умолчанию действие НЕ закрывает диалог: вызывайте api.close(value)
 * или укажите close:true; результат false отменяет автоматическое закрытие.
 * Для динамической валидации меняйте disabled у кнопки внутри api.element.
 * App.confirm(message) -> Promise<boolean>.
 * App.user() возвращает единственного исследователя; App.can(permission)
 * всегда true по плану, независимо от строки permission. Входа нет.
 * App.refresh() повторно отрисовывает текущий маршрут после изменения DB.
 * App.plan: полный список {id,name,route}; параметры детализации НЕ являются
 * ссылками навигации. Для ссылок на сущности подставляйте encodeURIComponent(id).
 * DB — внешний data.js, оболочка его не реализует. Точные имена entity:
 * «Профиль лазера», «Профиль материала», «Установка съёмки»,
 * «Калибровочная плата», «Пара входных файлов», «Наблюдение», «Запись знания»,
 * «Модель цветового пространства», «Передаточная функция», «План гравировки»,
 * «Целевой цвет», «Предложение эксперимента», «Отчёт после гравировки».
 * DB.list(entity,{q,filter,sort,dir,page,pageSize}) ->
 * {items,total,page,pageSize}; DB.get(entity,id); DB.create(entity,record);
 * DB.update(entity,id,patch); DB.remove(entity,id); DB.reset().
 * Оболочка вызывает только DB.reset(), принимает синхронный результат или
 * Promise. Она не определяет поля данных, значения filter/sort и доменные
 * функции: их контракт должны согласовать авторы data.js и экранов.
 * DB.user не используется. Состояние оболочки хранится в localStorage;
 * данные и черновики экранов сохраняют авторы data.js и экранов.
 * Допущения оболочки: первым разделом выбраны «Эксперименты»; детали
 * наблюдений, знаний и планов подсвечивают соответствующий основной раздел;
 * пустой и ошибочный режимы могут быть включены вместе, ошибка приоритетнее.
 * Единственная роль имеет все права, отдельного запретного сценария ролей нет.
 * Для HTML-строк используйте только собственную разметку; пользовательские
 * значения вставляйте через App.h или textContent.
 */
(function () {
  'use strict';
  const plan = [
    {id:'profiles',name:'Профили и условия измерения',route:'/profiles'},
    {id:'experiments',name:'Эксперименты и наблюдения',route:'/experiments'},
    {id:'ingest',name:'Добавить наблюдение',route:'/ingest'},
    {id:'analysis',name:'Анализ после гравировки',route:'/analysis/:id'},
    {id:'color-model',name:'Карта цветов и подбор параметров',route:'/colors'},
    {id:'knowledge',name:'Знание о цвете',route:'/knowledge/:id'},
    {id:'discrete',name:'Цветная гравировка',route:'/artwork'},
    {id:'continuous',name:'Непрерывная фотогравировка',route:'/photo'},
    {id:'plan',name:'План гравировки и экспорт',route:'/plans/:id'},
    {id:'designer',name:'Планировщик экспериментов',route:'/designer'}
  ];
  const navigation = [
    ['experiments','Эксперименты'],['color-model','Карта цветов'],
    ['discrete','Цветная гравировка'],['continuous','Фотогравировка'],
    ['designer','Планировщик экспериментов'],['profiles','Профили']
  ];
  const roles = [{id:'master',name:'Исследователь / мастер',role:'Единственный исследователь / мастер',permissions:['*']}];
  const key = 'titanium.shell.v1';
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(key) || '{}') || {}; } catch (_) {}
  const state = {empty:saved.empty === true,error:saved.error === true,userId:'master'};
  const screens = new Map();
  let started = false, content, titleNode, sidebar, menuButton, toastRegion, revision = 0;
  const openMenus = new Set();
  function persist() {
    try { localStorage.setItem(key,JSON.stringify(state)); }
    catch (_) { toast('Браузер не разрешает сохранение настроек. Они доступны до закрытия страницы.','warning'); }
  }
  function h(tag, attrs, ...children) {
    const el = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([name,value]) => {
      if (value == null) return;
      if (/^on[A-Z]/.test(name) && typeof value === 'function') el.addEventListener(name.slice(2).toLowerCase(),value);
      else if (name === 'class' || name === 'className') el.className = value;
      else if (name === 'text') el.textContent = value;
      else if (name === 'dataset') Object.assign(el.dataset,value);
      else if (name === 'style' && typeof value === 'object') Object.assign(el.style,value);
      else if (['value','checked','disabled','selected','multiple','hidden'].includes(name)) el[name] = value;
      else if (value !== false) el.setAttribute(name,value === true ? '' : String(value));
    });
    function append(child) {
      if (Array.isArray(child)) child.forEach(append);
      else if (child instanceof Node) el.append(child);
      else if (child != null && typeof child !== 'boolean') el.append(document.createTextNode(String(child)));
    }
    children.forEach(append);
    return el;
  }
  function insert(target,value) {
    target.replaceChildren();
    if (value instanceof Node) target.append(value);
    else if (typeof value === 'string') target.innerHTML = value;
    else if (value != null) throw new TypeError('Экран должен вернуть элемент или HTML-строку');
  }
  function user() { return {...roles[0],permissions:[...roles[0].permissions]}; }
  function closeMenus() { openMenus.forEach(close => close()); }
  function dropdown(label, body, className) {
    const panel = h('div',{class:'popover',hidden:true});
    const button = h('button',{class:'btn btn-small','aria-expanded':'false',type:'button'},label);
    const wrap = h('div',{class:'menu-wrap ' + (className || '')},button,panel);
    const close = () => {panel.hidden=true;button.setAttribute('aria-expanded','false');openMenus.delete(close);};
    button.addEventListener('click',() => {
      const show = panel.hidden;closeMenus();
      if (show) {panel.hidden=false;button.setAttribute('aria-expanded','true');openMenus.add(close);}
    });
    wrap.addEventListener('keydown',event => {
      if (event.key === 'Escape') {close();button.focus();event.stopPropagation();}
    });
    body(panel,close);
    return wrap;
  }
  function toast(message,kind='info') {
    if (!toastRegion) return () => {};
    const item = h('div',{class:'toast toast-' + (['success','error','warning'].includes(kind)?kind:'info'),role:kind==='error'?'alert':'status'},h('span',{},message));
    const remove = () => item.remove();
    item.append(h('button',{class:'btn btn-ghost btn-small',type:'button','aria-label':'Закрыть уведомление',onClick:remove},'×'));
    toastRegion.append(item);
    let timer = setTimeout(remove,6000);
    item.addEventListener('mouseenter',() => clearTimeout(timer));
    item.addEventListener('focusin',() => clearTimeout(timer));
    item.addEventListener('mouseleave',() => {timer=setTimeout(remove,6000);});
    return remove;
  }
  function modal({title,body,actions=[]}) {
    const previous = document.activeElement;
    const dialog = h('dialog',{class:'modal','aria-modal':'true'});
    const headingId = 'dialog-title-' + (++modal.counter);
    dialog.setAttribute('aria-labelledby',headingId);
    const bodyNode = h('div',{class:'modal-body'});
    insert(bodyNode,body);
    let resolve,finished=false,busy=false;
    const result = new Promise(done => {resolve=done;});
    const close = value => {
      if (finished) return;
      finished=true;dialog.close();dialog.remove();resolve(value);
      if (previous && previous.isConnected) previous.focus();
    };
    const api = {element:dialog,body:bodyNode,close,result};
    const footer = h('div',{class:'modal-actions'});
    actions.forEach(action => {
      const button = h('button',{type:'button',class:'btn' + (action.kind==='primary'?' btn-primary':action.kind==='danger'?' btn-danger':''),disabled:!!action.disabled},action.label);
      button.addEventListener('click',async event => {
        if (busy) return;
        busy=true;
        const buttons=[...dialog.querySelectorAll('button')];
        const disabled=buttons.map(b=>b.disabled);
        buttons.forEach(b=>{b.disabled=true;});
        dialog.setAttribute('aria-busy','true');
        try {
          const value = action.onClick ? await action.onClick(api,event) : undefined;
          if (action.close && value !== false) close(value);
        } catch (_) {toast('Не удалось выполнить действие. Повторите попытку.','error');}
        finally {
          busy=false;dialog.removeAttribute('aria-busy');
          buttons.forEach((b,i)=>{b.disabled=disabled[i];});
        }
      });
      footer.append(button);
    });
    dialog.append(h('div',{class:'modal-inner'},h('div',{class:'modal-heading'},h('h2',{id:headingId},title),h('button',{class:'btn btn-ghost btn-small',type:'button','aria-label':'Закрыть окно',onClick:()=>close(null)},'×')),bodyNode,footer));
    dialog.addEventListener('cancel',event=>{event.preventDefault();if(!busy)close(null);});
    dialog.addEventListener('click',event=>{
      const r=dialog.getBoundingClientRect();
      if(event.target===dialog&&!busy&&(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom))close(null);
    });
    document.body.append(dialog);dialog.showModal();
    return api;
  }
  modal.counter=0;
  function confirm(message) {
    const window = modal({title:'Подтверждение действия',body:h('p',{},message),actions:[
      {label:'Отмена',onClick:api=>api.close(false)},
      {label:'Подтвердить',kind:'primary',onClick:api=>api.close(true)}
    ]});
    return window.result.then(value=>value===true);
  }
  function errorCard(retry) {
    return h('section',{class:'error-state',role:'alert'},h('h2',{},'Не удалось загрузить данные'),h('p',{},state.error?'Включён демонстрационный режим ошибки. Отключите его в меню «Прототип» и повторите загрузку.':'Повторите попытку. Сохранённые данные остаются доступными.'),h('button',{class:'btn btn-primary',type:'button',onClick:retry},'Повторить'));
  }
  function load(fn) {
    const host=h('div',{class:'load-host'});
    let attempt=0;
    const run=async()=>{
      const current=++attempt;
      host.setAttribute('aria-busy','true');
      host.replaceChildren(h('div',{role:'status'},h('p',{class:'loading-label'},'Загружаем данные…'),h('div',{class:'skeleton skeleton-title','aria-hidden':'true'}),h('div',{class:'skeleton skeleton-block','aria-hidden':'true'}),h('div',{class:'skeleton','aria-hidden':'true'})));
      await new Promise(resolve=>setTimeout(resolve,350));
      try {
        if(state.error)throw new Error('Демонстрационная ошибка');
        const value=await fn();
        if(current===attempt)insert(host,value);
      } catch (_) {if(current===attempt)host.replaceChildren(errorCard(run));}
      finally {if(current===attempt)host.removeAttribute('aria-busy');}
    };
    run();return host;
  }
  function segments(route) {return route.split('/').filter(Boolean);}
  function match(route,path) {
    const expected=segments(route),actual=segments(path);
    if(expected.length!==actual.length)return null;
    const params={};
    for(let i=0;i<expected.length;i++) {
      let value;try{value=decodeURIComponent(actual[i]);}catch(_){return null;}
      if(expected[i].startsWith(':'))params[expected[i].slice(1)]=value;
      else if(expected[i]!==value)return null;
    }
    return params;
  }
  function parse() {
    const raw=location.hash.slice(1)||'/experiments';
    const separator=raw.indexOf('?');
    let path=separator<0?raw:raw.slice(0,separator);
    if(path.length>1)path=path.replace(/\/+$/,'');
    return {path,query:new URLSearchParams(separator<0?'':raw.slice(separator+1))};
  }
  function navigate(path) {
    if(typeof path!=='string'||!path.startsWith('/')||path.startsWith('//'))throw new Error('Укажите локальный маршрут, начинающийся с /');
    closeMenus();
    if(location.hash==='#'+path)refresh();else location.hash=path;
  }
  async function refresh() {
    if(!started)return;
    const current=++revision;
    closeMenus();sidebar.classList.remove('is-open');menuButton.setAttribute('aria-expanded','false');
    const {path,query}=parse();
    let descriptor=null,params=null;
    for(const item of plan) {const found=match(item.route,path);if(found){descriptor=item;params=found;break;}}
    if(!descriptor) {
      try { history.replaceState(null,'','#/experiments'); }
      catch (_) { location.hash='/experiments'; }
      return refresh();
    }
    const screen=screens.get(descriptor.id);
    titleNode.textContent=screen?.title||descriptor.name;
    document.title=titleNode.textContent+' — Цвет титана';
    const parents={ingest:'experiments',analysis:'experiments',plan:'experiments',knowledge:'color-model'};
    document.querySelectorAll('.nav-link').forEach(link=>{
      if(link.dataset.screen===(parents[descriptor.id]||descriptor.id))link.setAttribute('aria-current','page');
      else link.removeAttribute('aria-current');
    });
    const ctx={params,query,user:user(),proto:{empty:state.empty,error:state.error}};
    try {
      const value=screen?screen.render(ctx):h('section',{class:'empty-state'},h('h2',{},'Этот экран ещё создаётся.'),h('p',{},'Оболочка готова. Содержимое появится после подключения скрипта экрана.'));
      if(value&&typeof value.then==='function') {
        content.replaceChildren(h('div',{class:'skeleton skeleton-block',role:'status','aria-label':'Загружаем экран…'}));
        const resolved=await value;
        if(current!==revision)return;
        insert(content,resolved);
      } else insert(content,value);
    } catch (_) {if(current===revision)content.replaceChildren(errorCard(refresh));}
    if(current===revision)titleNode.focus({preventScroll:true});
  }
  function icon(index) {
    const paths=[
      '<path d="M9 3v6L4 18a2 2 0 0 0 2 3h12a2 2 0 0 0 2-3l-5-9V3M8 3h8M7 15h10"/>',
      '<circle cx="12" cy="12" r="9"/><path d="M12 3v18M3 12h18M6 6l12 12M6 18L18 6"/>',
      '<rect x="3" y="3" width="18" height="18" rx="4"/><path d="m5 17 5-5 4 3 3-6 4 6"/>',
      '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M7 16h2M11 13h2M15 10h2"/>',
      '<path d="M4 19V5M4 19h16M7 15l4-5 4 2 5-7"/>',
      '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="9" cy="6" r="2"/><circle cx="16" cy="12" r="2"/><circle cx="8" cy="18" r="2"/>'
    ];
    const el=h('span',{class:'nav-icon','aria-hidden':'true'});
    el.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'+paths[index]+'</svg>';
    return el;
  }
  function start() {
    if(started)return;
    const root=document.getElementById('app');
    if(!root)throw new Error('Не найден контейнер приложения');
    started=true;
    toastRegion=h('div',{class:'toast-region','aria-label':'Уведомления'});
    const proto=dropdown('Прототип',panel=>{
      panel.append(h('p',{},'Демонстрационные состояния не изменяют измерения.'));
      [['empty','Показать пустое состояние'],['error','Показать состояние ошибки']].forEach(([field,label])=>{
        panel.append(h('label',{class:'check'},h('input',{type:'checkbox',checked:state[field],onChange:event=>{state[field]=event.target.checked;persist();refresh();}}),h('span',{},label)));
      });
      panel.append(h('hr'));
      panel.append(h('button',{class:'btn',type:'button',onClick:async()=>{
        closeMenus();
        if(!await confirm('Восстановить демонстрационные данные? Сохранённые изменения будут заменены исходным набором.'))return;
        try {
          if(!window.DB||typeof window.DB.reset!=='function')throw new Error('Источник данных не подключён');
          await window.DB.reset();state.empty=false;state.error=false;persist();
          panel.querySelectorAll('input').forEach(input=>{input.checked=false;});
          refresh();toast('Демонстрационные данные восстановлены','success');
        }catch(_){toast('Не удалось восстановить демонстрационные данные. Проверьте подключение источника данных.','error');}
      }},'Сбросить демоданные'));
    });
    const signed=dropdown('Пользователь: исследователь / мастер',panel=>{
      panel.append(h('p',{},'Единственный пользователь. Все действия доступны; вход не требуется.'));
      roles.forEach(role=>panel.append(h('label',{class:'check'},h('input',{type:'radio',name:'shell-role',value:role.id,checked:true,onChange:()=>{state.userId=role.id;persist();refresh();}}),h('span',{},role.role))));
    },'user-menu');
    sidebar=h('aside',{class:'sidebar',id:'app-navigation','aria-label':'Разделы приложения'});
    const nav=h('nav',{class:'nav','aria-label':'Основная навигация'});
    navigation.forEach(([id,label],i)=>{
      const item=plan.find(p=>p.id===id);
      nav.append(h('a',{class:'nav-link',href:'#'+item.route,dataset:{screen:id}},icon(i),label));
    });
    sidebar.append(nav);
    menuButton=h('button',{class:'btn btn-small mobile-menu',type:'button','aria-controls':'app-navigation','aria-expanded':'false',onClick:()=>{
      const open=sidebar.classList.toggle('is-open');menuButton.setAttribute('aria-expanded',String(open));
      if(open)sidebar.querySelector('a').focus();
    }},'Меню');
    titleNode=h('h1',{tabindex:'-1'});
    content=h('div',{id:'screen-content'});
    root.replaceChildren(h('a',{class:'skip-link',href:'#main-content',onClick:event=>{event.preventDefault();document.getElementById('main-content').focus();}},'Перейти к содержимому'),h('header',{class:'app-header'},h('a',{class:'brand',href:'#/experiments'},'Цвет титана',h('small',{},'Измерения · Знания · Гравировка')),h('div',{class:'header-actions'},menuButton,signed,proto)),h('div',{class:'app-layout'},sidebar,h('main',{class:'main',id:'main-content',tabindex:'-1'},h('div',{class:'page-heading'},titleNode),h('p',{class:'demo-note'},'Кликабельный прототип · Демонстрационные данные и результаты обработки'),content)),toastRegion);
    document.addEventListener('click',event=>{
      if(!event.target.closest('.menu-wrap'))closeMenus();
      if(sidebar.classList.contains('is-open')&&!sidebar.contains(event.target)&&!menuButton.contains(event.target)){sidebar.classList.remove('is-open');menuButton.setAttribute('aria-expanded','false');}
    });
    document.addEventListener('keydown',event=>{
      if(event.key==='Escape'&&sidebar.classList.contains('is-open')){sidebar.classList.remove('is-open');menuButton.setAttribute('aria-expanded','false');menuButton.focus();}
    });
    window.addEventListener('hashchange',refresh);
    if(!location.hash) {
      try { history.replaceState(null,'','#/experiments'); }
      catch (_) { location.hash='/experiments'; }
    }
    refresh();
  }
  window.App={
    plan,register(screen){
      const descriptor=plan.find(item=>item.id===screen.id);
      if(!descriptor||screen.route!==descriptor.route||typeof screen.render!=='function')throw new Error('Проверьте идентификатор, маршрут и функцию экрана');
      screens.set(screen.id,screen);if(started)refresh();
    },h,navigate,toast,modal,confirm,load,start,refresh,user,
    can(){return true;},
    addStyles(css){const style=h('style',{},css);document.head.append(style);return style;}
  };
})();
