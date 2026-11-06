(function () {
  'use strict';
  const h = App.h;
  const KEY = 'titanium.color-model.view.v1';
  const stages = ['Измерено', 'Кандидат', 'Повторено', 'Валидировано', 'Производственное'];
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (_) {}
  const view = {profileId: saved.profileId || '', layer: ['Покрытие','Неопределённость','Стабильность'].includes(saved.layer) ? saved.layer : 'Покрытие', stage: saved.stage || '', questionable: !!saved.questionable, selected: saved.selected || ''};
  function persist() { try { localStorage.setItem(KEY, JSON.stringify(view)); } catch (_) { App.toast('Настройки просмотра доступны до закрытия страницы.', 'warning'); } }
  const all = (entity, filter) => DB.list(entity, {filter: filter || {}, pageSize: 10000, sort: 'id', dir: 'asc'}).items;
  const num = value => typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ru-RU', {maximumFractionDigits: 2}) : 'Не определено';
  const labText = value => value ? 'Lab ' + [value.L, value.a, value.b].map(num).join(' · ') : 'Нет исходных данных';
  const link = (text, route, cls) => h('a', {href: '#' + route, class: cls || ''}, text);
  const button = (text, fn, cls, disabled) => h('button', {type: 'button', class: 'btn ' + (cls || ''), onClick: fn, disabled: !!disabled}, text);
  const badge = (text, cls) => h('span', {class: 'badge ' + (cls || '')}, text);
  function color(lab) {
    if (!lab) return '#dce0e6';
    let y = (lab.L + 16) / 116, x = y + lab.a / 500, z = y - lab.b / 200;
    const inv = t => t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787;
    x = inv(x) * 0.95047; y = inv(y); z = inv(z) * 1.08883;
    const rgb = [3.2406*x-1.5372*y-0.4986*z, -0.9689*x+1.8758*y+0.0415*z, 0.0557*x-0.204*y+1.057*z];
    return 'rgb(' + rgb.map(v => Math.round(Math.max(0, Math.min(1, v > 0.0031308 ? 1.055 * v ** (1/2.4) - 0.055 : 12.92*v)) * 255)).join(',') + ')';
  }
  function swatch(lab, large) { return h('span', {class: 'swatch cm-swatch' + (large ? ' cm-large' : ''), style: {background: color(lab)}, role: 'img', 'aria-label': labText(lab)}); }
  function metric(label, value, detail) { return h('div', {class: 'cm-metric'}, h('small', {class: 'muted'}, label), h('strong', {}, value), detail ? h('small', {class: 'muted'}, detail) : null); }
  function vector(parameters, profile) {
    const p = parameters || {};
    return h('dl', {class: 'cm-vector'}, (profile.axes || []).map(a => [h('dt', {}, a.name), h('dd', {}, num(p[a.key]) + ' ' + a.unit)]), [
      ['Длительность импульса', p.pulseDuration, 'нс'], ['Интервал линий', p.lineInterval, 'мм'], ['Проходы', p.passes, '']
    ].map(([label, value, unit]) => [h('dt', {}, label), h('dd', {}, num(value) + (unit ? ' ' + unit : ''))]));
  }
  function observationsPanel(record) {
    const obs = (record.observationIds || []).map(id => DB.get('Наблюдение', id)).filter(Boolean);
    App.modal({title: 'Наблюдения-основания', body: h('div', {class: 'stack'}, h('p', {class: 'muted'}, 'Измерения неизменяемы. Неизвестный контекст указан отдельно.'), obs.length ? obs.map(o => h('article', {class: 'cm-evidence'}, h('div', {class: 'row'}, swatch(o.lab), h('div', {}, link(o.id, '/analysis/' + encodeURIComponent(o.pairId)), h('div', {}, labText(o.lab)))), h('p', {class: 'text-sm muted'}, 'Партия или лист: ' + (o.batch || 'Неизвестно') + ' · Фокус: ' + (o.focus == null ? 'Неизвестно' : num(o.focus)) + ' · Выравнивание: ' + (o.alignmentMethod || 'Неизвестно')), h('p', {class: 'text-sm'}, 'Допуск к модели: ' + (o.modelEligibility?.allowed ? 'Допущено' : 'Не допущено') + '. ' + (o.modelEligibility?.reason || 'Причина не определена')), h('p', {class: 'text-sm'}, 'Допуск к независимым повторам: ' + (o.repeatEligibility?.allowed ? 'Допущено' : 'Не определено') + '. ' + (o.repeatEligibility?.reason || 'Критерии не определены')))) : h('p', {}, 'Наблюдения-основания не найдены.')), actions: [{label: 'Закрыть', close: true}]});
  }
  function targetPanel(profile, model) {
    const result = h('div', {'aria-live': 'polite', class: 'cm-result'});
    const preview = swatch({L: 60, a: 10, b: 15}, true);
    const fields = {};
    const form = h('form', {noValidate: true});
    const fieldNodes = [['L','Светлота L',0,100,60],['a','Компонента a',-128,127,10],['b','Компонента b',-128,127,15]].map(([key,label,min,max,value]) => {
      const error = h('span', {id: 'cm-error-' + key, class: 'field-error', hidden: true});
      const input = h('input', {id: 'cm-target-' + key, type: 'number', step: 'any', min, max, required: true, value, 'aria-describedby': 'cm-error-' + key});
      fields[key] = {input, error, min, max};
      input.addEventListener('input', () => {
        result.replaceChildren(); input.removeAttribute('aria-invalid'); error.hidden = true;
        const target = read(false);
        if (target) { preview.style.background = color(target); preview.setAttribute('aria-label', labText(target)); }
      });
      return h('div', {class: 'field'}, h('label', {for: input.id}, label), input, h('span', {class: 'field-help'}, 'От ' + min + ' до ' + max), error);
    });
    function read(showErrors) {
      const target = {}; let valid = true;
      Object.entries(fields).forEach(([key, f]) => {
        const value = f.input.value.trim() === '' ? NaN : Number(f.input.value);
        const ok = Number.isFinite(value) && value >= f.min && value <= f.max;
        if (!ok) valid = false;
        if (showErrors) { f.error.hidden = ok; f.error.textContent = ok ? '' : 'Введите допустимую компоненту Lab'; f.input.setAttribute('aria-invalid', String(!ok)); }
        target[key] = value;
      });
      return valid ? target : null;
    }
    const submit = h('button', {type: 'submit', class: 'btn btn-primary'}, 'Подобрать параметры');
    form.append(h('div', {class: 'row cm-target-preview'}, preview, h('p', {class: 'muted'}, 'Демонстрационный прогноз. Точное физическое воспроизведение не гарантируется.')), h('div', {class: 'cm-lab-form'}, fieldNodes), submit, result);
    form.addEventListener('submit', async event => {
      event.preventDefault();
      const target = read(true);
      if (!target) { Object.values(fields).find(f => f.input.getAttribute('aria-invalid') === 'true').input.focus(); return; }
      submit.disabled = true; result.replaceChildren(h('p', {role: 'status'}, 'Подбираем параметры…'));
      try {
        await new Promise(resolve => setTimeout(resolve, 380));
        if (!model || !(model.observationIds || []).length) { result.replaceChildren(h('div', {class: 'alert alert-warning'}, 'Недостаточно данных для прогноза')); return; }
        const p = DB.predictColor(profile.id, target);
        if (!p.available || !Number.isFinite(p.confidence) || !Number.isFinite(p.expectedDeltaE) || !p.stability?.assessed) { result.replaceChildren(h('div', {class: 'alert alert-warning'}, 'Недостаточно данных для прогноза'), h('p', {class: 'muted'}, p.stability && !p.stability.assessed ? 'Стабильность не оценена: недостаточно независимых повторов.' : (p.message || 'Для прогноза нужны уверенность, ожидаемая ошибка и стабильность.'))); return; }
        result.replaceChildren(h('div', {class: 'alert ' + (p.outsideCoverage ? 'alert-warning' : 'alert-success')}, p.outsideCoverage ? 'Вне измеренного цветового пространства' : 'В пределах измеренного покрытия'), h('div', {class: 'row'}, swatch(target), h('div', {}, 'Целевой цвет', h('div', {class: 'muted'}, labText(target))), swatch(p.lab), h('div', {}, 'Прогнозируемый цвет', h('div', {class: 'muted'}, labText(p.lab)))), h('div', {class: 'cm-metrics'}, metric('Уверенность', num(p.confidence), 'Шкала от 0 до 1'), metric('Ожидаемая ошибка ΔE', num(p.expectedDeltaE)), metric('Стабильность', 'Оценена', 'Разброс: ' + num(p.stability.variance))), h('p', {}, 'Расстояние до целевого цвета ΔE: ' + num(p.deltaE)), vector(p.parameters, profile), h('div', {class: 'row'}, badge(p.stage || 'Стадия не определена'), p.questionable ? badge('Под вопросом', 'badge-warning') : null, link('Открыть знание', '/knowledge/' + encodeURIComponent(p.knowledgeId))), h('p', {class: 'field-help'}, 'Подбор исследовательский. Разрешение использовать параметры под вопросом в плане здесь не выдаётся.'));
      } catch (_) { result.replaceChildren(h('div', {class: 'alert alert-danger', role: 'alert'}, 'Не удалось подобрать параметры. Повторите подбор.')); }
      finally { submit.disabled = false; }
    });
    App.modal({title: 'Целевой цвет', body: form, actions: [{label: 'Закрыть', close: true}]});
  }
  function build(ctx) {
    const profiles = all('Профиль лазера').sort((a,b) => a.version-b.version);
    const requested = ctx.query.get('profileId') || ctx.query.get('profile');
    if (requested && profiles.some(p => p.id === requested)) view.profileId = requested;
    if (!profiles.some(p => p.id === view.profileId)) view.profileId = profiles[0]?.id || '';
    const profile = profiles.find(p => p.id === view.profileId);
    const root = h('div', {class: 'cm-screen stack'});
    if (!profile) return h('section', {class: 'empty-state'}, h('h2', {}, 'Нет измеренных цветов'), h('p', {}, 'Сначала настройте профиль лазера и добавьте наблюдения.'), h('div', {class: 'row'}, link('Профили', '/profiles', 'btn'), link('Добавить наблюдение', '/ingest', 'btn btn-primary')));
    const models = all('Модель цветового пространства', {profileId: profile.id});
    const model = models.sort((a,b) => String(a.updatedAt || a.createdAt || '').localeCompare(String(b.updatedAt || b.createdAt || ''))).at(-1);
    const records = ctx.proto.empty ? [] : all('Запись знания', {profileId: profile.id});
    const version = h('select', {id: 'cm-profile', onChange: event => { view.profileId = event.target.value; view.selected = ''; persist(); App.navigate('/colors?profileId=' + encodeURIComponent(view.profileId)); }}, profiles.map(p => h('option', {value: p.id, selected: p.id === profile.id}, 'Версия ' + p.version + ' · ' + p.name)));
    root.append(h('div', {class: 'toolbar'}, h('div', {class: 'field cm-profile'}, h('label', {for: 'cm-profile'}, 'Версия профиля'), version), h('div', {class: 'spacer'}), button('Целевой цвет', () => targetPanel(profile, model), 'btn-primary'), link('Спланировать эксперимент', '/designer?profileId=' + encodeURIComponent(profile.id) + (model ? '&modelId=' + encodeURIComponent(model.id) : ''), 'btn')));
    root.append(h('div', {class: 'cm-summary'}, metric('Модель', model ? model.version : 'Не построена', 'Версия профиля ' + profile.version), metric('Наблюдения-основания', ctx.proto.empty ? '0' : String(model?.observationIds?.length || 0)), metric('Измеренные образцы', String(records.length))), h('p', {class: 'field-help'}, 'Данные разных версий профиля не объединяются. Цвет на экране — приблизительное представление Lab.'));
    if (!records.length) {
      root.append(h('section', {class: 'empty-state'}, h('h2', {}, ctx.proto.empty ? 'Нет измеренных цветов' : 'Для этой версии профиля нет наблюдений'), h('p', {}, 'Измеренные цвета появятся после принятия пары файла LightBurn и фотографии со стенда.'), link('Добавить наблюдение', '/ingest?profileId=' + encodeURIComponent(profile.id), 'btn btn-primary')));
      return root;
    }
    const workspace = h('div'); root.append(workspace);
    function draw() {
      workspace.replaceChildren();
      const filtered = records.filter(k => (!view.stage || k.stage === view.stage) && (!view.questionable || k.questionable));
      const selected = records.find(k => k.id === view.selected) || filtered[0] || null;
      if (!view.selected && selected) { view.selected = selected.id; persist(); }
      const tabs = h('div', {class: 'tabs', role: 'tablist', 'aria-label': 'Слой карты'}, ['Покрытие','Неопределённость','Стабильность'].map(layer => h('button', {type: 'button', class: 'tab', role: 'tab', 'aria-selected': view.layer === layer, onClick: () => { view.layer = layer; persist(); draw(); }}, layer)));
      const stage = h('select', {id: 'cm-stage', onChange: e => { view.stage = e.target.value; persist(); draw(); }}, h('option', {value: '', selected: !view.stage}, 'Все стадии'), stages.map(s => h('option', {value: s, selected: view.stage === s}, s)));
      const filters = h('div', {class: 'toolbar'}, h('div', {class: 'field'}, h('label', {for: 'cm-stage'}, 'Стадия'), stage), h('label', {class: 'check'}, h('input', {type: 'checkbox', checked: view.questionable, onChange: e => { view.questionable = e.target.checked; persist(); draw(); }}), 'Под вопросом'), h('span', {class: 'muted text-sm'}, 'Показано: ' + filtered.length + ' из ' + records.length));
      const chart = h('div', {class: 'cm-chart', role: 'group', 'aria-label': 'Карта Lab: горизонтальная ось a, вертикальная ось b. Светлота L указана для каждого образца.'});
      const measured = records.filter(k => k.lab);
      if (measured.length > 1) {
        const xs = measured.map(k => (k.lab.a + 128) / 255 * 100), ys = measured.map(k => (127-k.lab.b) / 255 * 100);
        chart.append(h('div', {class: 'cm-coverage', style: {left: Math.min(...xs) + '%', top: Math.min(...ys) + '%', width: Math.max(3, Math.max(...xs)-Math.min(...xs)) + '%', height: Math.max(3, Math.max(...ys)-Math.min(...ys)) + '%'}, 'aria-hidden': 'true'}));
      }
      chart.append(h('span', {class: 'cm-axis cm-axis-a'}, 'a: −128 → 127'), h('span', {class: 'cm-axis cm-axis-b'}, 'b: 127 → −128'));
      filtered.filter(k => k.lab).forEach(k => {
        let annotation = '';
        if (view.layer === 'Неопределённость') annotation = ' · Уверенность ' + num(k.confidence) + ' · Ожидаемая ошибка ΔE ' + num(k.expectedDeltaE);
        if (view.layer === 'Стабильность') annotation = ' · ' + (k.stability?.assessed ? 'Разброс ' + num(k.stability.variance) : 'Стабильность не оценена');
        chart.append(h('button', {type: 'button', class: 'cm-point' + (selected?.id === k.id ? ' cm-selected' : ''), style: {left: ((k.lab.a+128)/255*100) + '%', top: ((127-k.lab.b)/255*100) + '%', background: color(k.lab)}, title: labText(k.lab) + annotation, 'aria-label': labText(k.lab) + ' · ' + k.stage + annotation + (k.questionable ? ' · Под вопросом' : ''), 'aria-pressed': selected?.id === k.id, onClick: () => { view.selected = k.id; persist(); draw(); }}, h('span', {class: 'cm-point-label'}, view.layer === 'Неопределённость' ? num(k.confidence) : view.layer === 'Стабильность' ? (k.stability?.assessed ? num(k.stability.variance) : '—') : 'L ' + num(k.lab.L))));
      });
      const mapCard = h('section', {class: 'card cm-map-card'}, h('h2', {}, 'Измеренное цветовое пространство Lab'), h('p', {class: 'muted text-sm'}, view.layer === 'Покрытие' ? 'Проекция a × b. Светлота L подписана у каждого образца.' : view.layer === 'Неопределённость' ? 'Число у образца — уверенность от 0 до 1. Ожидаемая ошибка доступна в карточке.' : 'Число у образца — разброс. «—» означает: стабильность не оценена.'), chart, h('div', {class: 'cm-legend'}, h('span', {}, h('i', {class: 'cm-dot'}), 'Измеренный образец'), h('span', {}, h('i', {class: 'cm-area-key'}), 'Расчётная область покрытия')), h('p', {class: 'field-help'}, 'Расчётная область — проекция границ измерений; она не гарантирует достижимость всех внутренних цветов.'), !filtered.length ? h('div', {class: 'alert'}, 'Нет записей с выбранными фильтрами.', button('Сбросить фильтры', () => { view.stage = ''; view.questionable = false; persist(); draw(); }, 'btn-small')) : null);
      const detail = h('section', {class: 'card cm-detail', 'aria-label': 'Выбранный цвет'});
      if (selected) {
        const obs = (selected.observationIds || []).map(id => DB.get('Наблюдение', id)).filter(Boolean);
        detail.append(h('div', {class: 'row'}, swatch(selected.lab, true), h('div', {}, h('h2', {}, 'Выбранный цвет'), h('p', {class: 'muted'}, labText(selected.lab)))), h('div', {class: 'row'}, badge(selected.stage), selected.questionable ? badge('Под вопросом', 'badge-warning') : null), h('div', {class: 'cm-metrics'}, metric('Уверенность', num(selected.confidence), 'Шкала от 0 до 1'), metric('Ожидаемая ошибка ΔE', num(selected.expectedDeltaE)), metric('Стабильность', selected.stability?.assessed ? 'Оценена' : 'Не оценена', selected.stability?.assessed ? 'Разброс: ' + num(selected.stability.variance) : 'Недостаточно независимых повторов')), h('p', {}, 'Допустимые независимые повторы: ' + (selected.independentRepeats == null ? 'Не определено' : selected.independentRepeats)), vector(selected.parameters, profile), h('div', {class: 'row'}, link('Открыть знание', '/knowledge/' + encodeURIComponent(selected.id), 'btn btn-primary'), button('Наблюдения', () => observationsPanel(selected))), h('h3', {class: 'cm-subheading'}, 'Измерения и производный цвет'), h('p', {class: 'text-sm muted'}, 'Производный: ' + labText(selected.lab)), obs.length ? h('ul', {class: 'cm-measurements'}, obs.map(o => h('li', {}, link(labText(o.lab), '/analysis/' + encodeURIComponent(o.pairId)), h('small', {class: 'muted'}, ' · Партия: ' + (o.batch || 'Неизвестно') + ' · Фокус: ' + (o.focus == null ? 'Неизвестно' : num(o.focus)))))) : h('p', {class: 'muted'}, 'Наблюдения-основания не найдены.'), !filtered.some(k => k.id === selected.id) ? h('p', {class: 'field-help'}, 'Выбранный цвет сохранён; текущие фильтры скрывают его на карте.') : null);
      } else detail.append(h('p', {}, 'Выберите цветовой образец.'));
      const concerns = h('section', {class: 'card'}, h('h2', {}, 'Области для следующего эксперимента'), h('div', {class: 'cm-summary'}, h('div', {}, h('h3', {}, 'Пробелы и неопределённость'), model?.uncertainty?.length ? model.uncertainty.map(u => h('p', {}, u.label + ' · ' + num(u.value))) : h('p', {class: 'muted'}, 'Расчётные области не определены.')), h('div', {}, h('h3', {}, 'Нестабильные области'), model?.unstableRegions?.length ? model.unstableRegions.map(u => h('p', {}, u.knowledgeId ? link(u.label, '/knowledge/' + encodeURIComponent(u.knowledgeId)) : u.label, ' · Разброс: ' + num(u.variance))) : h('p', {class: 'muted'}, 'Нестабильные области не отмечены.'))));
      workspace.append(tabs, filters, h('div', {class: 'cm-layout'}, mapCard, detail), concerns);
    }
    draw();
    root.append(h('details', {class: 'cm-assumptions'}, h('summary', {}, 'Допущения представления'), h('p', {}, 'Для карты выбрана проекция a × b с отдельной подписью L. Пунктирная область показывает границы измерений в проекции. Цветовые образцы преобразованы из Lab в экранный цвет с ограничением диапазона; это не цветопроба. Подбор использует демонстрационный алгоритм ближайшего измеренного цвета и евклидов ΔE. Настройки просмотра сохраняются в этом браузере.')));
    return root;
  }
  App.addStyles(`
    .cm-screen{gap:20px}.cm-profile{max-width:540px;flex:1}.cm-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}.cm-summary>.cm-metric{background:white;border:1px solid var(--line);border-radius:14px;padding:18px}.cm-metric{display:flex;flex-direction:column;gap:5px;min-width:0}.cm-metric strong{font-size:20px;letter-spacing:-.3px}.cm-layout{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(300px,1fr);gap:20px;margin-bottom:20px}.cm-map-card{min-width:0;align-self:start}.cm-chart{height:390px;position:relative;margin:28px 28px 42px 32px;border:1px solid #ccd3dd;border-radius:8px;background:linear-gradient(#dfe4ec80 1px,transparent 1px),linear-gradient(90deg,#dfe4ec80 1px,transparent 1px),#fafbfd;background-size:25% 25%}.cm-coverage{position:absolute;border:2px dashed #7192ba;background:#0066d60b;border-radius:12px;min-width:8px;min-height:8px}.cm-axis{position:absolute;font-size:11px;color:var(--muted);white-space:nowrap}.cm-axis-a{bottom:-29px;left:50%;transform:translateX(-50%)}.cm-axis-b{left:-25px;top:50%;writing-mode:vertical-rl;transform:translateY(-50%) rotate(180deg)}.cm-point{position:absolute;transform:translate(-50%,-50%);width:30px;height:30px;border:3px solid white;border-radius:50%;box-shadow:0 1px 5px #0004;z-index:2;padding:0}.cm-point:hover,.cm-point:focus-visible{z-index:5}.cm-point.cm-selected{outline:3px solid var(--accent);outline-offset:3px;z-index:4}.cm-point-label{position:absolute;left:50%;top:32px;transform:translateX(-50%);font-size:10px;color:#303846;background:#fffffff2;border-radius:4px;padding:1px 3px;white-space:nowrap;pointer-events:none}.cm-legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;margin-bottom:12px;color:var(--muted)}.cm-legend>span{display:flex;align-items:center;gap:7px}.cm-dot{width:12px;height:12px;border-radius:50%;background:#7184a1}.cm-area-key{width:18px;height:12px;border:1px dashed #7192ba;background:#0066d60b}.cm-metrics{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin:22px 0}.cm-detail .cm-metric strong{font-size:17px}.cm-vector{display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;font-size:13px;border-top:1px solid var(--line);padding-top:16px;margin:16px 0 24px}.cm-vector dt{color:var(--muted)}.cm-vector dd{margin:0;text-align:right}.cm-large{width:70px;height:70px;flex:none;border-radius:16px}.cm-swatch{vertical-align:middle}.cm-detail>.row{margin-bottom:12px}.cm-detail .row p{margin-bottom:0}.cm-subheading{margin-top:24px}.cm-measurements{padding-left:18px;font-size:13px}.cm-measurements li{margin-bottom:12px}.cm-evidence{padding:16px;border:1px solid var(--line);border-radius:12px}.cm-evidence p{margin:12px 0 0}.cm-lab-form{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.cm-target-preview{margin-bottom:20px;flex-wrap:nowrap}.cm-target-preview p{margin:0}.cm-result{margin-top:20px}.cm-result>.alert{margin-bottom:16px}.cm-result>.row{margin-bottom:16px}.cm-result .cm-metric strong{font-size:17px}.cm-assumptions{font-size:13px;color:var(--muted)}.cm-assumptions summary{cursor:pointer}.cm-assumptions p{margin-top:12px;max-width:900px}@media(max-width:1200px){.cm-layout{grid-template-columns:1fr}.cm-chart{height:350px}.cm-detail .cm-metrics{max-width:650px}}@media(max-width:600px){.cm-summary{grid-template-columns:1fr;gap:12px}.cm-metrics{grid-template-columns:1fr;gap:14px}.cm-lab-form{grid-template-columns:1fr}.cm-chart{height:300px;margin-right:15px}.cm-profile{max-width:100%;min-width:100%!important}.cm-layout{display:block}.cm-map-card{margin-bottom:16px}.cm-target-preview{align-items:flex-start}.cm-detail>.row .btn{width:100%}}
  `);
  App.register({id: 'color-model', route: '/colors', title: 'Карта цветов и подбор параметров', render(ctx) {
    const host = App.load(() => build(ctx));
    const label = host.querySelector('.loading-label');
    if (label) label.textContent = 'Строим карту цветов…';
    return host;
  }});
})();
