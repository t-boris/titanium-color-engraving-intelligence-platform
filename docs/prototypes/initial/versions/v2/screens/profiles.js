(function () {
  'use strict';
  const h = App.h;
  const E = {laser:'Профиль лазера', material:'Профиль материала', stand:'Установка съёмки', model:'Модель цветового пространства'};
  const draftKey = 'titanium.profiles.drafts.v1';
  let drafts = {};
  try { drafts = JSON.parse(localStorage.getItem(draftKey) || '{}') || {}; } catch (_) {}
  function remember() { try { localStorage.setItem(draftKey, JSON.stringify(drafts)); } catch (_) {} }
  function all(entity) { return DB.list(entity, {pageSize:10000, sort:'version', dir:'asc'}).items; }
  function link(route, label) { return h('a', {href:'#' + route}, label); }
  function button(label, action, primary) { return h('button', {type:'button', class:'btn' + (primary ? ' btn-primary' : ''), onClick:action}, label); }
  function format(value) { return value == null || value === '' ? 'Не задано' : String(value); }
  App.addStyles('.profiles-screen .profiles-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:24px}.profiles-screen .profiles-summary>div{padding:16px;background:#fafbfc;border:1px solid var(--line);border-radius:12px}.profiles-screen .profiles-summary strong{display:block;font-size:18px}.profiles-screen .profiles-summary small{color:var(--muted)}.profiles-screen .profiles-axis{padding:14px;border:1px solid var(--line);border-radius:12px}.profiles-screen .profiles-axis strong{display:block}.profiles-screen .profiles-intro{max-width:760px}.profiles-screen .profiles-save-error{margin-bottom:16px}.profiles-screen .profiles-form{max-width:900px}.profiles-screen .profiles-versions{min-width:240px;flex:1}.profiles-screen details summary{cursor:pointer;font-weight:550}.profiles-screen details p{margin-top:12px}.profiles-screen .profiles-tabs{overflow:auto;flex-wrap:nowrap}.profiles-screen .profiles-tabs button{white-space:nowrap}@media(max-width:600px){.profiles-screen .profiles-summary{grid-template-columns:1fr}.profiles-screen .profiles-versions{min-width:100%}}');
  App.register({
    id:'profiles', route:'/profiles', title:'Профили и условия измерения',
    render(ctx) {
      const loading = App.load(() => build(ctx));
      const label = loading.querySelector('.loading-label');
      if (label) label.textContent = 'Загружаем профили…';
      return loading;
    }
  });
  function build(ctx) {
    const profiles = ctx.proto.empty ? [] : all(E.laser);
    const materials = ctx.proto.empty ? [] : all(E.material);
    const stands = ctx.proto.empty ? [] : all(E.stand);
    let profileId = ctx.query.get('profile') || profiles[0]?.id || '';
    if (!profiles.some(p => p.id === profileId)) profileId = profiles[0]?.id || '';
    let active = ['laser','material','stand','rules'].includes(ctx.query.get('tab')) ? ctx.query.get('tab') : 'laser';
    if (ctx.query.get('tab') === 'Правила оценки') active = 'rules';
    const root = h('div', {class:'profiles-screen stack'});
    const tabs = h('div', {class:'tabs profiles-tabs', role:'tablist', 'aria-label':'Настройки профилей'});
    const content = h('div', {role:'tabpanel', id:'profiles-panel'});
    root.append(h('p', {class:'muted profiles-intro'}, 'Один лазер, титан и фиксированный фотостенд. Сохранённая версия связывает параметры гравировки с измерениями.'), tabs, content);
    if (!profiles.length) root.insertBefore(h('div', {class:'alert', role:'status'}, 'Настройте профиль лазера и стенд'), tabs);
    const names = [['laser','Лазер'],['material','Титан'],['stand','Стенд'],['rules','Правила оценки']];
    const tabButtons = names.map(([key, name]) => {
      const b = h('button', {type:'button', class:'tab', role:'tab', id:'profiles-tab-' + key, 'aria-controls':'profiles-panel', onClick:() => {active = key; draw();}}, name);
      b.addEventListener('keydown', event => {
        let next = names.findIndex(x => x[0] === active);
        if (event.key === 'ArrowRight') next = (next + 1) % names.length;
        else if (event.key === 'ArrowLeft') next = (next + names.length - 1) % names.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = names.length - 1;
        else return;
        event.preventDefault(); active = names[next][0]; draw(); tabButtons[next].focus();
      });
      tabs.append(b); return b;
    });
    function draw() {
      tabButtons.forEach((b, i) => {b.setAttribute('aria-selected', String(names[i][0] === active)); b.tabIndex = names[i][0] === active ? 0 : -1;});
      content.setAttribute('aria-labelledby', 'profiles-tab-' + active);
      content.replaceChildren();
      if (active === 'laser') laser();
      if (active === 'material') material();
      if (active === 'stand') stand();
      if (active === 'rules') rules();
    }
    function current() { return profiles.find(p => p.id === profileId) || null; }
    function versionPicker() {
      const select = h('select', {class:'select', id:'profiles-version', disabled:!profiles.length, onChange:event => {profileId = event.target.value; draw();}});
      if (!profiles.length) select.append(h('option', {value:''}, 'Профиль ещё не создан'));
      profiles.forEach(p => select.append(h('option', {value:p.id, selected:p.id === profileId}, 'Версия ' + p.version + ' · ' + p.name)));
      return h('div', {class:'field profiles-versions'}, h('label', {for:'profiles-version'}, 'Версия профиля'), select);
    }
    function formShell(title, intro) {
      const form = h('form', {class:'card profiles-form', noValidate:true});
      const errorBox = h('div', {class:'profiles-save-error', hidden:true, role:'alert'});
      form.append(h('h2', {}, title), intro ? h('p', {class:'muted'}, intro) : null, errorBox);
      content.append(form);
      return {form, errorBox};
    }
    function valuesFor(key, record, defaults) {
      const fingerprint = JSON.stringify(record || null);
      const stored = drafts[key];
      if (!stored || stored.fingerprint !== fingerprint) drafts[key] = {fingerprint, values:{...defaults}};
      return drafts[key].values;
    }
    function field(form, key, label, values, type, options) {
      const id = 'profiles-' + active + '-' + key;
      const error = h('span', {class:'field-error', id:id + '-error', hidden:true}, 'Введите допустимое значение');
      const input = h('input', {id, type:type || 'text', value:values[key] ?? '', ...(options || {}), 'aria-describedby':id + '-error', onInput:event => {values[key] = event.target.value; remember(); input.removeAttribute('aria-invalid'); error.hidden = true;}});
      const wrap = h('div', {class:'field'}, h('label', {for:id}, label), input, error);
      form.append(wrap);
      return {input, error, invalid(bad) {input.setAttribute('aria-invalid', String(bad)); error.hidden = !bad; return !bad;}};
    }
    function wire(form, errorBox, fields, validate, action, success) {
      const submit = h('button', {class:'btn btn-primary', type:'submit'}, success.label);
      const actions = h('div', {class:'form-actions'}, submit);
      form.append(actions);
      let busy = false;
      const attempt = async () => {
        if (busy) return;
        const data = validate();
        if (!data) {Object.values(fields).find(f => f.input.getAttribute('aria-invalid') === 'true')?.input.focus(); return;}
        busy = true; errorBox.hidden = true;
        const controls = [...form.querySelectorAll('input,select,button')];
        const previous = controls.map(x => x.disabled);
        controls.forEach(x => {x.disabled = true;});
        form.setAttribute('aria-busy','true'); submit.textContent = 'Сохраняем…';
        try { await action(data); }
        catch (e) {
          errorBox.hidden = false;
          errorBox.replaceChildren(h('div', {class:'alert alert-danger'}, h('p', {}, 'Не удалось сохранить настройки'), h('p', {class:'text-sm'}, e.message || 'Повторите попытку.'), button('Повторить', attempt)));
          if (e.fields) Object.keys(e.fields).forEach(k => fields[k]?.invalid(true));
        } finally {busy = false; controls.forEach((x,i) => {x.disabled = previous[i];}); form.removeAttribute('aria-busy'); submit.textContent = success.label;}
      };
      form.addEventListener('submit', event => {event.preventDefault(); attempt();});
    }
    function numeric(raw, positive, integer) {return String(raw).trim() !== '' && Number.isFinite(Number(raw)) && (positive ? Number(raw) > 0 : Number(raw) >= 0) && (!integer || Number.isSafeInteger(Number(raw)));}
    function laser() {
      content.append(h('div', {class:'toolbar'}, versionPicker()));
      const p = current();
      if (p) {
        const observations = DB.list('Наблюдение', {filter:{profileId:p.id}, pageSize:1}).total;
        const plans = DB.list('План гравировки', {filter:{profileId:p.id}, pageSize:1}).total;
        content.append(h('div', {class:'profiles-summary'}, h('div', {}, h('strong', {}, 'Версия ' + p.version), h('small', {}, 'Сохранённый профиль')), h('div', {}, h('strong', {}, observations), h('small', {}, 'Привязанные наблюдения')), h('div', {}, h('strong', {}, plans), h('small', {}, 'Привязанные планы'))));
      }
      const key = 'laser:' + (p?.id || (ctx.proto.empty ? 'demo-empty' : 'new'));
      const v = valuesFor(key, p, {name:p?.name || '', pulseDuration:p?.pulseDuration ?? '', lineInterval:p?.lineInterval ?? '', passes:p?.passes ?? ''});
      const {form, errorBox} = formShell('Профиль лазера', 'Изменение констант создаёт новую версию. Данные разных версий не объединяются автоматически.');
      const fields = {};
      fields.name = field(form, 'name', 'Название', v);
      const axes = p?.axes || [{name:'Мощность',unit:'%',min:5,max:95},{name:'Частота',unit:'кГц',min:20,max:200},{name:'Скорость',unit:'мм/с',min:100,max:3000}];
      form.append(h('h3', {}, 'Переменные оси'), h('div', {class:'grid grid-3'}, axes.map(a => h('div', {class:'profiles-axis'}, h('strong', {}, a.name), h('span', {class:'muted'}, a.min + '–' + a.max + ' ' + a.unit))), h('p', {class:'field-help', style:{marginTop:'12px'}}, 'Мощность, частота и скорость наблюдения читаются из фактически приложенного файла LightBurn.'), h('h3', {}, 'Константы профиля'));
      const grid = h('div', {class:'grid grid-3'}); form.append(grid);
      fields.pulseDuration = field(grid, 'pulseDuration', 'Длительность импульса, нс', v, 'number', {min:0, step:'any'});
      fields.lineInterval = field(grid, 'lineInterval', 'Интервал линий, мм', v, 'number', {min:0, step:'any'});
      fields.passes = field(grid, 'passes', 'Проходы', v, 'number', {min:1, step:1});
      wire(form,errorBox,fields,() => {
        const valid = [fields.name.invalid(!String(v.name).trim()), fields.pulseDuration.invalid(!numeric(v.pulseDuration,true)), fields.lineInterval.invalid(!numeric(v.lineInterval,true)), fields.passes.invalid(!numeric(v.passes,true,true))].every(Boolean);
        return valid ? {name:v.name.trim(),pulseDuration:Number(v.pulseDuration),lineInterval:Number(v.lineInterval),passes:Number(v.passes)} : null;
      }, async data => {
        const result = await DB.run('saveLaserProfile', p?.id || null, data, false);
        if (result.requiresConfirmation) {
          const table = h('table', {class:'table'}, h('thead', {}, h('tr', {}, ['Константа','Прежнее значение','Новое значение'].map(t => h('th', {scope:'col'}, t)))), h('tbody', {}, [['pulseDuration','Длительность импульса, нс'],['lineInterval','Интервал линий, мм'],['passes','Проходы']].map(([k,label]) => h('tr', {}, h('th', {scope:'row'}, label), h('td', {}, result.previous[k]), h('td', {}, result.next[k])))));
          const modalError = h('div', {role:'alert'});
          App.modal({title:'Новая версия профиля', body:h('div', {}, h('p', {}, 'Существующие измерения сохранят прежнюю версию и полный вектор параметров.'), h('div', {class:'table-wrap'}, table), modalError), actions:[{label:'Отмена', onClick:api => api.close()}, {label:'Создать версию', kind:'primary', onClick:async api => {
            try {const saved = await DB.run('saveLaserProfile',p.id,data,true); delete drafts[key]; remember(); api.close(); App.toast('Создана новая версия профиля','success'); App.navigate('/profiles?profile=' + encodeURIComponent(saved.id));}
            catch (_) {modalError.replaceChildren(h('p', {class:'alert alert-danger'}, 'Не удалось сохранить настройки. Повторите создание версии.'));}
          }}]});
        } else {delete drafts[key]; remember(); App.toast('Настройки сохранены','success'); App.navigate('/profiles?profile=' + encodeURIComponent(result.id));}
      }, {label:'Сохранить профиль'});
      const assumption = h('details', {class:'card', style:{marginTop:'16px'}}, h('summary', {}, 'Допущения прототипа'), h('p', {class:'muted'}, 'Для первого профиля используются демонстрационные диапазоны: мощность 5–95 %, частота 20–200 кГц, скорость 100–3000 мм/с. Диапазоны показаны для просмотра; добавление осей не предусмотрено. Единицы констант: нс и мм. Вкладки «Титан» и «Стенд» редактируют первую сохранённую запись; дополнительные записи не создаются при наличии существующей.'));
      content.append(assumption);
    }
    function material() {
      const record = materials[0] || null;
      const key = 'material:' + (record?.id || (ctx.proto.empty ? 'demo-empty' : 'new'));
      const v = valuesFor(key,record,{name:record?.name || '',batch:record?.batch || ''});
      const {form,errorBox} = formShell('Профиль материала','Единственное семейство материала — титан. Партия или лист в наблюдении необязательны.');
      form.append(h('p', {}, h('span', {class:'badge'}, 'Семейство: Титан')));
      const fields = {name:field(form,'name','Название',v),batch:field(form,'batch','Идентификатор партии или листа · необязательно',v)};
      form.append(h('p', {class:'field-help'}, 'Пустая партия или лист отображаются в наблюдениях как «Неизвестно».'));
      wire(form,errorBox,fields,() => fields.name.invalid(!String(v.name).trim()) ? {name:v.name.trim(),family:'Титан',batch:v.batch.trim() || null} : null, async data => {
        if (record) await DB.run('update',E.material,record.id,data); else await DB.run('create',E.material,data);
        delete drafts[key]; remember(); App.toast('Настройки сохранены','success'); App.refresh();
      }, {label:'Сохранить материал'});
    }
    function stand() {
      const record = stands[0] || null;
      const key = 'stand:' + (record?.id || (ctx.proto.empty ? 'demo-empty' : 'new'));
      const v = valuesFor(key,record,{name:record?.name || '',camera:record?.camera || '',lighting:record?.lighting || '',angle:record?.angle ?? '',referenceCard:record?.referenceCard || ''});
      const {form,errorBox} = formShell('Установка съёмки','Фиксируйте камеру, свет и геометрию съёмки. Повторяемость стенда оценивается по повторным фотографиям того же изделия.');
      const fields = {};
      [['name','Название стенда'],['camera','Камера и стойка'],['lighting','Освещение'],['angle','Угол съёмки · число или описание'],['referenceCard','Эталонная карта']].forEach(([k,label]) => {fields[k] = field(form,k,label,v);});
      form.append(h('div', {class:'field'}, h('span', {class:'field-label'}, 'Формат съёмки'), h('span', {class:'badge'}, 'RAW')), h('p', {class:'alert alert-warning'}, 'Без обнаруженного эталона наблюдения не создаются и модель не обновляется.'));
      wire(form,errorBox,fields,() => {
        const valid = Object.keys(fields).map(k => fields[k].invalid(!String(v[k]).trim())).every(Boolean);
        if (!valid) return null;
        const data = Object.fromEntries(Object.keys(fields).map(k => [k,String(v[k]).trim()]));
        data.format = 'RAW'; return data;
      }, async data => {
        if (record) await DB.run('update',E.stand,record.id,data); else await DB.run('create',E.stand,data);
        delete drafts[key]; remember(); App.toast('Настройки сохранены','success'); App.refresh();
      }, {label:'Сохранить стенд'});
    }
    function rules() {
      content.append(h('div', {class:'toolbar'},versionPicker()));
      const p = current();
      if (!p) {content.append(h('section', {class:'empty-state'}, h('h2', {}, 'Сначала настройте профиль лазера'), button('Настроить профиль', () => {active='laser';draw();}, true))); return;}
      const model = all(E.model).filter(m => m.profileId === p.id).slice(-1)[0] || null;
      const agreed = !!model?.rules?.agreed;
      const key = 'rules:' + p.id;
      const v = valuesFor(key,model,{repeatThreshold:model?.repeatThreshold ?? '',deltaTolerance:model?.deltaTolerance ?? '',varianceThreshold:model?.varianceThreshold ?? ''});
      const {form,errorBox} = formShell('Правила оценки','Пороги применяются к совместимой версии профиля. Ввод чисел сам по себе не означает согласование общих критериев.');
      form.append(h('div', {class:'alert ' + (agreed ? 'alert-warning' : ''), role:'status'}, agreed ? 'Условно согласованные демонстрационные критерии. Этот сценарий не подтверждает производственную пригодность настроек.' : 'Автоматическая валидация ожидает определения правил качества и независимости повторов'), h('p', {class:'text-sm muted', style:{marginTop:'16px'}}, 'Состояние согласования: ' + (agreed ? model.rules.specification : 'Общие критерии качества и независимости не согласованы')));
      const fields = {};
      fields.repeatThreshold = field(form,'repeatThreshold','Порог независимых повторов',v,'number',{min:1,step:1,placeholder:'Не задано'});
      fields.deltaTolerance = field(form,'deltaTolerance','Допуск отклонения ΔE',v,'number',{min:0,step:'any',placeholder:'Не задано'});
      fields.varianceThreshold = field(form,'varianceThreshold','Порог дисперсии',v,'number',{min:0,step:'any',placeholder:'Не задано'});
      form.append(h('p', {class:'field-help'}, 'Сохранённые значения: повторы — ' + format(model?.repeatThreshold) + '; допуск ΔE — ' + format(model?.deltaTolerance) + '; дисперсия — ' + format(model?.varianceThreshold) + '. Пустое поле сохраняется как «Не задано».'), h('p', {class:'alert'}, 'Повторная фотография того же изделия не считается независимой гравировкой. Отсутствие материала, партии или фокуса не снижает право наблюдения на учёт повторов.'));
      wire(form,errorBox,fields,() => {
        const valid = Object.keys(fields).map(k => fields[k].invalid(String(v[k]).trim() !== '' && !numeric(v[k],k === 'repeatThreshold',k === 'repeatThreshold'))).every(Boolean);
        return valid ? Object.fromEntries(Object.keys(fields).map(k => [k,String(v[k]).trim() === '' ? null : Number(v[k])])) : null;
      }, async data => {await DB.run('saveThresholds',p.id,data);delete drafts[key];remember();App.toast('Настройки сохранены','success');App.refresh();}, {label:'Сохранить пороги'});
      content.append(h('p', {class:'muted', style:{marginTop:'16px'}}, 'Измерения и производные знания проверяются отдельно. ', link('/colors?profile=' + encodeURIComponent(p.id),'Карта цветов')));
    }
    draw();
    return root;
  }
})();
